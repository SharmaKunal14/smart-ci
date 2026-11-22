import importlib.util
import json
from pathlib import Path

import pytest

from smartci.selection import digest


@pytest.fixture
def comparison(monkeypatch):
    directory = Path(__file__).parents[1] / "examples/textual"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "agent_comparison", directory / "compare_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def triple(tmp_path):
    run = {
        "status": "completed",
        "event": "pull_request",
        "run_attempt": 1,
        "head_sha": "b" * 40,
        "created_at": "2026-11-23T01:00:00Z",
        "html_url": "https://example.invalid/run",
    }
    write(tmp_path / "run.json", run)
    jobs = []
    for index, mode in enumerate(("native", "smart", "assisted-replay")):
        directory = tmp_path / f"textual-{mode}-1"
        directory.mkdir()
        jobs.append(
            {
                "name": mode,
                "status": "completed",
                "conclusion": "failure",
                "html_url": f"https://example.invalid/job/{index}",
                "started_at": "2026-11-23T01:00:02Z",
                "completed_at": f"2026-11-23T01:00:{10 + index}Z",
            }
        )
        write(
            directory / "execution.json",
            {
                "base": "a" * 40,
                "head": "b" * 40,
                "mode": mode,
                "execution": "full",
                "targets": None,
                "planning_error": None,
                "exit_code": 1,
                "planning_seconds": index,
                "test_seconds": 4.0,
            },
        )
        (directory / "junit.xml").write_text(
            '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"><testcase classname="tests.a" name="bug"><failure>expected</failure></testcase></testsuite></testsuites>'
        )
    write(tmp_path / "jobs.json", {"jobs": jobs})
    selection = {
        "selected": ["a"],
        "fallback": ["INCOMPLETE_EVIDENCE"],
        "comparison": {"base": "a" * 40, "head": "b" * 40},
    }
    write(tmp_path / "textual-smart-1/selection.json", selection)
    report = {
        "status": "finished",
        "model_calls": 0,
        "model_effectiveness_measured": False,
        "baseline": selection,
        "final": selection,
    }
    report["digest"] = digest(report)
    write(tmp_path / "textual-assisted-replay-1/investigation.json", report)
    write(
        tmp_path / "textual-assisted-replay-1/comparison.json",
        {"head": "b" * 40, "base": "a" * 40, "repeatable": True, "inventory_cases": 1},
    )
    return tmp_path


def test_only_hosted_complete_outcomes_and_total_timings_count(comparison, triple):
    result = comparison.compare(triple)
    assert result["trigger_to_result_savings_seconds"] == {
        "smart": -1.0,
        "assisted-replay": -2.0,
    }
    assert result["total_runner_seconds"] == 27.0
    assert result["observed_missed_failures"] == {"smart": 0, "assisted-replay": 0}
    assert result["subset_executed"] is False


@pytest.mark.parametrize(
    "defect",
    [
        "unfinished",
        "rerun",
        "wrong_revision",
        "subset",
        "missing_results",
        "different_failure",
        "tampered_report",
    ],
)
def test_invalid_hosted_comparison_cannot_pass(comparison, triple, defect):
    if defect in ("unfinished", "rerun"):
        path = triple / "run.json"
        value = json.loads(path.read_text())
        value.update(
            {"status": "in_progress"} if defect == "unfinished" else {"run_attempt": 2}
        )
        write(path, value)
    elif defect == "different_failure":
        path = triple / "textual-assisted-replay-1/junit.xml"
        path.write_text(path.read_text().replace('name="bug"', 'name="different"'))
    elif defect == "tampered_report":
        path = triple / "textual-assisted-replay-1/investigation.json"
        value = json.loads(path.read_text())
        value["model_effectiveness_measured"] = True
        write(path, value)
    else:
        path = triple / "textual-assisted-replay-1/execution.json"
        value = json.loads(path.read_text())
        value.update(
            {
                "wrong_revision": {"head": "c" * 40},
                "subset": {"execution": "subset"},
                "missing_results": {"exit_code": 124},
            }[defect]
        )
        write(path, value)
    with pytest.raises(ValueError):
        comparison.compare(triple)
