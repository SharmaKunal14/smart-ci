import hashlib
import importlib.util
import subprocess
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


@pytest.fixture
def native_tree(tmp_path, monkeypatch):
    def git(*args):
        return (
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )
            .stdout.decode()
            .strip()
        )

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("*.generated\n")
    (tmp_path / "WORKSPACE.bazel").write_text("# original\n")
    (tmp_path / "README.md").write_text("original\n")
    git("add", ".")
    git("commit", "-qm", "native baseline")
    monkeypatch.setattr(module, "UPSTREAM", git("rev-parse", "HEAD"))
    return tmp_path, git


def test_native_baseline_allows_only_approved_harness_changes(native_tree):
    root, git = native_tree
    (root / ".smartci").mkdir()
    (root / ".smartci/baseline.py").write_text("# harness\n")
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/pilot.yml").write_text("# workflow\n")
    module.verify_source(root)
    git("add", ".")
    git("commit", "-qm", "pilot harness")
    module.verify_source(root)


@pytest.mark.parametrize("path", ["WORKSPACE.bazel", "README.md", ".gitignore"])
def test_native_baseline_rejects_changes_outside_old_path_allowlist(native_tree, path):
    root, git = native_tree
    (root / path).write_text("changed\n")
    with pytest.raises(subprocess.CalledProcessError):
        module.verify_source(root)
    git("add", path)
    with pytest.raises(subprocess.CalledProcessError):
        module.verify_source(root)
    git("commit", "-qm", "unexpected input change")
    with pytest.raises(subprocess.CalledProcessError):
        module.verify_source(root)


@pytest.mark.parametrize("path", ["extra.bzl", "ignored.generated", ".github/config"])
def test_native_baseline_rejects_untracked_and_ignored_inputs(native_tree, path):
    root, _ = native_tree
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unexpected native input\n")
    with pytest.raises(ValueError, match="untracked"):
        module.verify_source(root)


def test_profile_drift_never_silently_changes_native_semantics(monkeypatch):
    raw = b"/usr/local/bin/bazel test ... --test_env=SAME --copt=SAME\n"
    with pytest.raises(ValueError, match="review required"):
        module.targeted_profile(raw)
    monkeypatch.setattr(module, "PROFILE_SHA256", hashlib.sha256(raw).hexdigest())
    derived = module.targeted_profile(raw)
    assert derived.replace(module.TARGET.encode(), b"...") == raw
    assert module.targeted_profile(raw, "full") == raw
    with pytest.raises(ValueError, match="unsupported"):
        module.targeted_profile(raw, "test-filter")
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
