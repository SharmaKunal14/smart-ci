import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/abseil"))
try:
    SPEC = importlib.util.spec_from_file_location(
        "native_diagnostics", ROOT / "examples/abseil/diagnostics.py"
    )
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
finally:
    sys.path.pop(0)


def test_profile_drift_never_silently_changes_native_semantics(monkeypatch):
    raw = b"/usr/local/bin/bazel test ... --test_env=SAME --copt=SAME\n"
    with pytest.raises(ValueError, match="review required"):
        module.targeted_profile(raw)
    monkeypatch.setattr(module, "PROFILE_SHA256", hashlib.sha256(raw).hexdigest())
    derived = module.targeted_profile(raw)
    assert derived.replace(module.TARGET.encode(), b"...") == raw
    duplicate = raw + raw
    monkeypatch.setattr(module, "PROFILE_SHA256", hashlib.sha256(duplicate).hexdigest())
    with pytest.raises(ValueError, match="ambiguous"):
        module.targeted_profile(duplicate)


def test_resource_snapshot_never_reads_environment_or_command_line(tmp_path):
    for name in module.PROC_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("0\n")
    proc = tmp_path / "100"
    proc.mkdir()
    (proc / "comm").write_text("apport\n")
    (proc / "environ").write_text("SECRET_MUST_NOT_BE_READ")
    (proc / "cmdline").write_text("SECRET_MUST_NOT_BE_READ")
    result = module.resource_snapshot(tmp_path)
    assert result["helper_process_counts"]["apport"] == 1
    assert "SECRET" not in str(result)
    (tmp_path / "meminfo").write_bytes(b"x" * 16385)
    assert module.resource_snapshot(tmp_path)["meminfo"] is None


def test_diagnostic_preserves_process_exit_and_bounds_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "resource_snapshot", lambda: {"test": True})
    profile = tmp_path / "profile.sh"
    profile.write_text("exit 3\n")
    result = module.run_profile(profile, tmp_path, {}, timeout=5)
    assert result[0] == 3
    assert result[2] is None
    profile.write_text("sleep 20\n")
    result = module.run_profile(profile, tmp_path, {}, timeout=0)
    assert result[0] == 124
    assert result[2] == "DIAGNOSTIC_TIMEOUT"


def test_hosted_diagnostic_has_upstream_history_and_no_model_credentials():
    workflow = (ROOT / "examples/abseil/diagnostic-workflow.yml").read_text()
    assert "fetch-depth: 0" in workflow
    assert "persist-credentials: false" in workflow
    assert "secrets." not in workflow
    assert "contents: read" in workflow and "timeout-minutes: 14" in workflow
