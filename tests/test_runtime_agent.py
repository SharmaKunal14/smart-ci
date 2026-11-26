import importlib
import json
from pathlib import Path

import pytest
from test_runtime_observer import observe, repository
from test_runtime_scope import commit

from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.engine import investigate
from smartci.investigation.models import Limits, Location
from smartci.investigation.replay import ImportReplay
from smartci.investigation.runtime_scope import ObservedRun, candidate
from smartci.selection import digest


@pytest.fixture
def trial(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "examples/textual"))
    agent = importlib.import_module("runtime_agent")
    root = repository(
        tmp_path,
        {
            ".gitignore": "__pycache__/\n.pytest_cache/\n",
            "src/library.py": "\ndef value(): return 1\n",
            "conftest.py": "import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).parent/'src'))\n",
            "test_a.py": "import library\ndef test_a(): assert library.value() == 1\n",
            "test_b.py": "import library\ndef test_b(): pass\n",
        },
    )
    output = tmp_path / "observation.json"
    result = observe(
        root,
        output,
        extra=(
            "--smartci-observation-contexts",
            "--smartci-observation-engine",
            "monitoring",
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = ObservedRun.model_validate_json(output.read_bytes())
    (root / "src/library.py").write_text("\ndef value(): return 2\n")
    head = commit(root)
    initial = candidate(root, observed.commit, head, output.read_bytes())
    assert initial["candidate_files"] == ["test_a.py"]
    inputs = agent.inputs_from_observation(root, observed.commit, head, observed, {})
    limits = Limits(steps=4)
    report = investigate(
        inputs,
        Broker(root, inputs, PythonImports(["src"]), limits),
        ImportReplay([Location(revision=head, path="test_b.py")]),
        limits,
    )
    return agent, root, initial, inputs, report


def test_agent_evidence_adds_test_without_claiming_production_or_live_effectiveness(
    trial,
):
    agent, root, initial, inputs, report = trial
    assert (
        not inputs.base.complete
        and not inputs.head.complete
        and not inputs.inventory.complete
    )
    assert all(not d for d in inputs.head.dependencies.values())
    result = agent.expand(root, initial, inputs, report)
    assert result["agent_added_files"] == ["test_b.py"]
    assert result["candidate_files"] == ["test_a.py", "test_b.py"]
    assert result["model_calls"] == 0  # Fixture only, never a live-model claim.
    assert result["omission_authorized"] is False
    assert report["final"]["execution"] == "full"
    assert result == agent.expand(root, initial, inputs, report)


@pytest.mark.parametrize("mutation", ["source", "target", "revision", "integrity"])
def test_forged_accepted_facts_fail_independent_source_replay(trial, mutation):
    agent, root, initial, inputs, report = trial
    edge = report["accepted_graph"]["evidence"][0]
    if mutation == "source":
        edge["source_digest"] = "a" * 64
    elif mutation == "target":
        edge["target"] = "test_a.py"
    elif mutation == "revision":
        edge["revision"] = "a" * 40
    else:
        report["status"] = "changed"
    if mutation != "integrity":
        report["digest"] = digest({k: v for k, v in report.items() if k != "digest"})
    with pytest.raises((ValueError, KeyError)):
        agent.expand(root, initial, inputs, report)


def test_unfinished_agent_preserves_full_execution(trial):
    agent, root, initial, inputs, report = trial
    report["status"] = "provider_error"
    report["digest"] = digest({k: v for k, v in report.items() if k != "digest"})
    result = agent.expand(root, initial, inputs, report)
    assert result["candidate_files"] == initial["inventory_files"]
    assert "AGENT_INCOMPLETE" in result["fallback"]


def test_initial_context_is_bounded_before_budget_or_network():
    from smartci.investigation.openai_provider import OpenAIProvider

    p = OpenAIProvider(
        None, None, "a" * 64, initial_context={"purpose": "public advisory input"}
    )
    assert json.loads(p.messages[-1]["content"])["purpose"] == "public advisory input"
    with pytest.raises(ValueError):
        OpenAIProvider(None, None, "a" * 64, initial_context={"text": "x" * 8192})
