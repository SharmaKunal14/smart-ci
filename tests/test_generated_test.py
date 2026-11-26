import importlib
import json
from pathlib import Path

import pytest
from test_live_provider import ModelAPI
from test_model_budget import MemoryStore

from smartci.investigation.budget import Ledger
from smartci.investigation.openai_provider import OpenAIProvider
from smartci.selection import digest


@pytest.fixture
def generator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "examples/textual"))
    return importlib.import_module("generate_test")


def response_provider(generator, source):
    store = MemoryStore()
    api = ModelAPI(store)
    api.output["output"][1]["content"][0]["text"] = json.dumps(
        {
            "kind": "submit_test",
            "source": source,
            "rationale": "Fixture, not live evidence",
        }
    )
    return (
        generator.TestProvider(api, Ledger(store, "approved"), digest("generation")),
        api,
        store,
    )


def test_generation_contract_does_not_expand_production_actions(generator):
    p, api, store = response_provider(generator, "def test_example(): assert True\n")
    production = OpenAIProvider(api, Ledger(store, "approved"), digest("production"))
    with pytest.raises(ValueError):
        production.next_action("{}")
    assert p.attempts == 0


def test_generated_text_is_saved_exactly_and_never_executed(generator, tmp_path):
    source = "raise RuntimeError('would fail if executed')\n"
    p, _, _ = response_provider(generator, source)
    report = generator.propose(p, None, {"coverage_gap": "fixture"}, tmp_path)
    assert report["status"] == "proposal_requires_review"
    assert (tmp_path / generator.TEST).read_bytes() == source.encode()
    assert report["executed"] is False and report["human_edits"] is False
    assert (
        report["accounting"]["model_calls"] == 1
    )  # Fake API plumbing, not live evidence.


def test_invalid_python_preserves_proposal_but_cannot_pass(generator, tmp_path):
    p, _, _ = response_provider(generator, "async def broken(:")
    report = generator.propose(p, None, {}, tmp_path)
    assert report["status"] == "error"
    assert report["error_type"] == "SyntaxError"
    assert (tmp_path / generator.TEST).exists()
    assert report["executed"] is False


def test_disabled_campaign_makes_no_api_calls(generator, tmp_path):
    p, api, store = response_provider(generator, "assert True")
    store.state.enabled = False
    report = generator.propose(p, None, {}, tmp_path)
    assert report["status"] == "error" and api.calls == []
    assert not (tmp_path / generator.TEST).exists()


def test_coverage_gap_rejects_executed_body_or_missing_target(generator):
    source = (
        b"class MarkdownTableContent:\n async def _update_rows(self):\n  return 1\n"
    )
    xml = b'<coverage><class filename="widgets/_markdown.py"><lines><line number="2" hits="1"/><line number="3" hits="0"/></lines></class></coverage>'
    assert generator.coverage_gap(xml, source)["executable_body_line_hits"] == {3: 0}
    for invalid in (
        xml.replace(b'number="3" hits="0"', b'number="3" hits="1"'),
        xml.replace(b"widgets/", b"other/"),
        b"<!DOCTYPE coverage>" + xml,
    ):
        with pytest.raises(ValueError):
            generator.coverage_gap(invalid, source)


def test_source_access_rejects_model_mutations_and_arbitrary_paths(generator):
    for action in (
        {"kind": "execute", "command": "pytest"},
        {
            "kind": "read_source",
            "revision": "a" * 40,
            "path": "../secrets",
            "start": 1,
            "lines": 1,
        },
        {
            "kind": "submit_test",
            "source": "pass",
            "rationale": "x",
            "path": "conftest.py",
        },
    ):
        with pytest.raises(ValueError):
            generator.Action.model_validate(action)


def test_workflow_never_executes_generated_code_with_model_credentials():
    workflow = Path(".github/workflows/textual-generated-test.yml").read_text()
    generation, execution = workflow.split("  reviewed-test:")
    reviewed, controls = execution.split("  original-suite:")
    assert workflow.count("secrets.OPENAI_API_KEY") == 1
    assert "OPENAI_API_KEY" not in execution and "GITHUB_TOKEN" not in execution
    assert "sha256sum --check" in reviewed
    assert "--mode native" in controls
    assert "poetry" not in generation and "pytest" not in generation
    assert "vars.SMARTCI_TEXTUAL_GENERATION_TRIAL == 'repair-one'" in generation
    assert "disable_model_campaign.py" in generation
    assert "persist-credentials: true" not in workflow


def test_repair_feedback_is_the_original_working_failure(generator):
    feedback = generator.RepairFeedback.model_validate_json(
        Path("examples/textual/generated-test-working-feedback.json").read_bytes()
    )
    proposal = json.loads(
        Path(
            "docs/benchmarks/textual-generated-test-proposal-2026-11-27.json"
        ).read_text()
    )
    assert feedback.previous_source == proposal["events"][-1]["action"]["source"]
    assert feedback.generation_digest == proposal["digest"]
    assert feedback.working_job == "generated-working"
    assert "f1a9d30986616a922871020df233f883ead8dc82" not in feedback.model_dump_json()


@pytest.mark.parametrize("change", ["revision", "job", "source", "coverage", "heldout"])
def test_repair_rejects_wrong_or_extra_feedback(generator, change):
    value = json.loads(
        Path("examples/textual/generated-test-working-feedback.json").read_text()
    )
    if change == "revision":
        value["revision"] = "a" * 40
    elif change == "job":
        value["working_job"] = "generated-defect"
    elif change == "source":
        value["previous_source"] += "\n"
    elif change == "coverage":
        value["target_body_line_hits"]["694"] = 1
    else:
        value["defect_results"] = "do not send this to the model"
    with pytest.raises(ValueError):
        generator.RepairFeedback.model_validate_json(json.dumps(value))


def test_repair_workflow_separates_working_and_heldout_execution():
    workflow = Path(".github/workflows/textual-generated-test.yml").read_text()
    assert "== 'verify-working' && '[\"working\"]'" in workflow
    assert "== 'verify-heldout' && '[\"defect\"]'" in workflow
    assert "generated-test-working-feedback.json" in workflow
    assert "check_generated_test.py" in workflow


@pytest.mark.parametrize(
    "defect", [None, "zero_hit", "missing_line", "skipped", "failed"]
)
def test_working_acceptance_requires_real_body_coverage_and_passing_cases(
    generator, defect
):
    check = importlib.import_module("check_generated_test")
    lines = {n: 1 for n in check.BODY_LINES}
    if defect == "zero_hit":
        lines[694] = 0
    if defect == "missing_line":
        lines.pop(694)
    coverage = (
        '<coverage><class filename="widgets/_markdown.py"><lines>'
        + "".join(f'<line number="{n}" hits="{v}"/>' for n, v in lines.items())
        + "</lines></class></coverage>"
    ).encode()
    tag = {"skipped": '<skipped type="pytest.skip"/>', "failed": "<failure/>"}.get(
        defect, ""
    )
    outcomes = (
        f'<testsuites><testsuite tests="1" errors="0" failures="{int(defect == "failed")}" skipped="{int(defect == "skipped")}"><testcase classname="generated" name="test_rows">{tag}</testcase></testsuite></testsuites>'
    ).encode()
    if defect is None:
        check.verify(coverage, outcomes)
    else:
        with pytest.raises(ValueError):
            check.verify(coverage, outcomes)
