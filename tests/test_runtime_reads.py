"""Read provenance must separate observed phases without granting skip authority."""

import hashlib
import json
import sys
import threading

import pytest
from pydantic import ValidationError
from test_runtime_observer import observe, repository

from smartci.adapters import runtime_reads
from smartci.adapters.runtime_observer import Observation
from smartci.adapters.runtime_reads import ReadProvenance
from smartci.discovery.models import Snapshot
from smartci.selection import Report, digest


def trace(root, tmp_path):
    output, provenance = tmp_path / "observation.json", tmp_path / "reads.json"
    result = observe(
        root,
        output,
        extra=(
            "--smartci-observation-contexts",
            "--smartci-observation-engine",
            "monitoring",
            "-p",
            "smartci.adapters.runtime_reads",
            "--smartci-read-provenance",
            str(provenance),
        ),
    )
    return result, output, provenance


def test_real_reads_distinguish_test_protocol_from_reporting_and_preserve_redaction(
    tmp_path,
):
    private = tmp_path / "private-do-not-record.txt"
    private.write_text("sensitive contents")
    root = repository(
        tmp_path,
        {
            "source.py": "def value(): return 'do-not-record-source-contents'\n",
            "test_a.py": (
                "from pathlib import Path\n"
                "def test_read():\n"
                "    assert Path('source.py').read_text()\n"
                f"    assert Path({str(private)!r}).read_text()\n"
            ),
            "conftest.py": (
                "import pytest\nfrom pathlib import Path\n"
                "@pytest.hookimpl(hookwrapper=True)\n"
                "def pytest_runtestloop(session):\n"
                "    yield\n"
                "    Path('source.py').read_text()\n"
                "def pytest_sessionfinish(session):\n"
                "    Path('source.py').read_text()\n"
            ),
        },
    )
    result, observation, output = trace(root, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    raw = output.read_text()
    report = json.loads(raw)
    assert (
        report["observation_sha256"]
        == hashlib.sha256(observation.read_bytes()).hexdigest()
    )
    assert report["digest"] == digest(
        {k: v for k, v in report.items() if k != "digest"}
    )
    events = [e for e in report["events"] if e["path"] == "source.py"]
    assert {e["lifecycle"] for e in events} == {
        "test_protocol",
        "after_tests",
        "session_finish",
    }
    during = next(e for e in events if e["lifecycle"] == "test_protocol")
    assert during["context"] == "test_a.py"
    assert any(f.get("path") == "test_a.py" for f in during["stack"])
    assert report["completed_protocols"] == 1
    assert report["diagnostics"] == []
    assert report["omission_authorized"] is False
    for value in (str(private), str(root), "sensitive contents", "do-not-record"):
        assert value not in raw
    for contract in (Snapshot, Report):
        with pytest.raises(ValidationError):
            contract.model_validate(report)


def test_reporting_failure_remains_a_native_failure(tmp_path):
    root = repository(
        tmp_path,
        {
            "test_a.py": "def test_a(): pass\n",
            "conftest.py": "def pytest_sessionfinish(session): session.exitstatus = 3\n",
        },
    )
    result, observation, output = trace(root, tmp_path)
    assert result.returncode == 3
    assert json.loads(observation.read_text())["exit_code"] == 3
    assert json.loads(output.read_text())["omission_authorized"] is False


@pytest.mark.parametrize("limit", ["MAX_EVENTS", "MAX_BYTES"])
def test_limits_deduplication_and_other_thread_label(tmp_path, monkeypatch, limit):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    observer = Observation(root, tmp_path / "observation.json")
    state = ReadProvenance(observer, tmp_path / "reads.json")
    state.active = True
    for _ in range(2):
        thread = threading.Thread(
            target=state.audit, args=("open", (str(root / "test_a.py"),))
        )
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(state.events) == 1
    assert json.loads(next(iter(state.events.values())))["lifecycle"] == "other_thread"
    monkeypatch.setattr(runtime_reads, limit, 0)
    state.audit("open", (str(root / "test_a.py"),))
    assert "READ_PROVENANCE_LIMIT_REACHED" in state.diagnostics
    assert len(state.events) == 1


def test_stack_and_output_boundaries(tmp_path, monkeypatch):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    observer = Observation(root, tmp_path / "observation.json")
    for output in (root / "new.json", observer.output):
        with pytest.raises(ValueError):
            ReadProvenance(observer, output)
    existing = tmp_path / "existing.json"
    existing.write_text("preserved")
    with pytest.raises(ValueError):
        ReadProvenance(observer, existing)
    assert existing.read_text() == "preserved"
    state = ReadProvenance(observer, tmp_path / "reads.json")
    monkeypatch.setattr(runtime_reads, "MAX_FRAMES", 1)
    frames, truncated = state.stack(sys._getframe())
    assert truncated and len(frames) == 1
    assert all(f["family"] == "other" for f in frames)


def test_missing_scoped_observer_is_rejected(tmp_path):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    result = observe(
        root,
        tmp_path / "observation.json",
        extra=(
            "-p",
            "smartci.adapters.runtime_reads",
            "--smartci-read-provenance",
            str(tmp_path / "reads.json"),
        ),
    )
    assert result.returncode != 0
    assert "requires scoped runtime observation" in result.stderr
    assert not (tmp_path / "reads.json").exists()


def test_missing_audit_hook_is_disclosed(tmp_path, monkeypatch):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    observer = Observation(root, tmp_path / "observation.json")
    state = ReadProvenance(observer, tmp_path / "reads.json")
    monkeypatch.setattr(sys, "addaudithook", lambda hook: None)
    monkeypatch.setattr(sys, "audit", lambda event: None)
    state.start()
    assert "READ_AUDIT_HOOK_NOT_CONFIRMED" in state.diagnostics
