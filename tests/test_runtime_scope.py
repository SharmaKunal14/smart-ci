"""Runtime candidates are falsifiable hypotheses, never trusted selection reports."""

import json
import subprocess

import pytest
from pydantic import ValidationError
from test_runtime_observer import observe, repository

from smartci.discovery.models import Snapshot
from smartci.investigation.runtime_scope import candidate
from smartci.selection import Report, digest


def commit(root):
    subprocess.run(["git", "add", "."], cwd=root, check=True, timeout=10)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=f@example.invalid",
            "commit",
            "-qm",
            "change",
        ],
        cwd=root,
        check=True,
        timeout=10,
    )
    return (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    )


@pytest.fixture
def evidence(tmp_path):
    root = repository(
        tmp_path,
        {
            ".gitignore": "__pycache__/\n.pytest_cache/\n",
            "library.py": "def value(): return 1\ndef unobserved(): return 7\n",
            "test_a.py": "import library\ndef test_a(): assert library.value() == 1\n",
            "test_b.py": "def test_b(): assert True\n",
            "test_process.py": "import subprocess, sys\ndef test_process(): subprocess.run([sys.executable, '-c', 'pass'], check=True)\n",
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
    data = json.loads(output.read_text())
    (root / "library.py").write_text(
        "def value(): return 2\ndef unobserved(): return 8\n"
    )
    head = commit(root)
    return root, data["commit"], head, data


def encoded(data):
    unsigned = {k: v for k, v in data.items() if k != "digest"}
    return json.dumps(unsigned | {"digest": digest(unsigned)}).encode()


def test_real_observation_retains_callers_processes_and_uncertainty(evidence):
    root, base, head, data = evidence
    report = candidate(root, base, head, encoded(data))
    assert report == candidate(root, base, head, encoded(data))
    assert report["candidate_files"] == ["test_a.py", "test_process.py"]
    assert report["unobserved_changed_callables"] == ["unobserved"]
    assert report["required_execution"] == "full"
    assert report["omission_authorized"] is False
    assert report["fallback"] == []
    for contract in (Report, Snapshot):
        with pytest.raises(ValidationError):
            contract.model_validate(report)


@pytest.mark.parametrize("context", ["@shared", "@other-thread", "unknown-owner"])
def test_shared_function_entries_expand_to_full_inventory(evidence, context):
    root, base, head, data = evidence
    data["contexts"][context] = {"code_entries": ["library.py:1"]}
    report = candidate(root, base, head, encoded(data))
    assert report["candidate_files"] == report["inventory_files"]


def test_source_reads_remain_explicit_unresolved_evidence(evidence):
    root, base, head, data = evidence
    data["contexts"]["@shared"] = {"open_attempts": ["library.py"]}
    report = candidate(root, base, head, encoded(data), ["test_b.py"])
    assert "@shared" in report["unresolved_source_read_contexts"]
    assert report["candidate_files"] == report["inventory_files"]


@pytest.mark.parametrize(
    "mutation", ["tree", "observer", "failed", "diagnostic", "path", "digest"]
)
def test_invalid_or_incomplete_maps_are_rejected(evidence, mutation):
    root, base, head, data = evidence
    if mutation == "tree":
        data["tracked_blobs"]["library.py"] = "0" * 40
    elif mutation == "observer":
        data["observer_sha256"] = "0" * 64
    elif mutation == "failed":
        data["exit_code"] = 1
    elif mutation == "diagnostic":
        data["diagnostics"].append("OBSERVATION_LIMIT_REACHED")
    elif mutation == "path":
        data["contexts"]["test_a.py"]["code_entries"] = ["../secret.py:1"]
    raw = encoded(data) if mutation != "digest" else b"{}"
    with pytest.raises(ValueError):
        candidate(root, base, head, raw)


def test_old_process_observations_require_full_fallback(evidence):
    root, base, head, data = evidence
    for context in data["contexts"].values():
        context.pop("process_events", None)
    report = candidate(root, base, head, encoded(data))
    assert "PROCESS_CALLER_NOT_RECORDED" in report["fallback"]
    assert report["candidate_files"] == report["inventory_files"]


@pytest.mark.parametrize(
    "path,content",
    [
        ("library.py", "VALUE = 2\ndef value(): return VALUE\n"),
        ("config.json", "{}"),
        ("new.py", "def new(): pass\n"),
        ("test_a.py", "def test_new(): pass\n"),
        ("library.py", None),
    ],
)
def test_broad_added_deleted_and_test_changes_fall_back(evidence, path, content):
    root, base, _, data = evidence
    if content is None:
        (root / path).unlink()
    else:
        (root / path).write_text(content)
    report = candidate(root, base, commit(root), encoded(data))
    assert report["fallback"]
    assert report["candidate_files"] == report["inventory_files"]


def test_wrong_base_and_unknown_mandatory_test_are_rejected(evidence):
    root, base, head, data = evidence
    with pytest.raises(ValueError):
        candidate(root, "a" * 40, head, encoded(data))
    with pytest.raises(ValueError):
        candidate(root, base, head, encoded(data), ["unknown.py"])
