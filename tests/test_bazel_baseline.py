import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "bazel_baseline", Path(__file__).parents[1] / "examples/abseil/baseline.py"
)
assert SPEC is not None and SPEC.loader is not None
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def events(path, status="PASSED", code=0, complete=True):
    rows = [
        {
            "id": {"testSummary": {"label": "//lib:test"}},
            "testSummary": {"overallStatus": status},
        },
        {"finished": {"exitCode": {"code": code}}},
    ]
    if complete:
        rows.append({"lastMessage": True})
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_bazel_summary_preserves_native_failed_target(tmp_path):
    path = tmp_path / "events.json"
    events(path, "FAILED", 3)
    result = baseline.summarize_events(path)
    assert result["test_target_count"] == 1
    assert result["test_targets"] == {"//lib:test": "FAILED"}
    assert result["exit_code"] == 3


def test_protobuf_default_zero_exit_code_is_supported(tmp_path):
    path = tmp_path / "events.json"
    events(path)
    path.write_text(path.read_text().replace('"code": 0', '"name": "SUCCESS"'))
    assert baseline.summarize_events(path)["exit_code"] == 0


@pytest.mark.parametrize("defect", ["truncated", "duplicate", "unknown_status"])
def test_invalid_build_evidence_is_not_accepted(tmp_path, defect):
    path = tmp_path / "events.json"
    events(
        path,
        "UNKNOWN" if defect == "unknown_status" else "PASSED",
        complete=defect != "truncated",
    )
    if defect == "duplicate":
        path.write_text(path.read_text() + "\n" + path.read_text())
    with pytest.raises(ValueError):
        baseline.summarize_events(path)


@pytest.mark.parametrize("code", [0, 3, 124])
def test_native_profile_exit_and_timeout_are_preserved(tmp_path, monkeypatch, code):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "evidence"
    calls = []

    def run(command, environment, timeout):
        calls.append((command, environment, timeout))
        if code == 124:
            return 124
        events(output / "native.bep.json", "FAILED" if code else "PASSED", code)
        return code

    monkeypatch.chdir(root)
    monkeypatch.setattr(baseline, "run_native", run)
    monkeypatch.setattr(
        baseline.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        baseline.os, "environ", {"KOKORO_KEYSTORE_DIR": "not-available"}
    )
    monkeypatch.setattr(sys, "argv", ["baseline", "--output", str(output)])
    assert baseline.main() == code
    command, environment, timeout = calls[0]
    assert command == ["bash", "ci/linux_gcc-latest_libstdcxx_bazel.sh"]
    assert timeout == 1200
    assert "KOKORO_KEYSTORE_DIR" not in environment
    assert environment["STD"] == "c++17"
    assert environment["COMPILATION_MODE"] == "fastbuild"
    assert "cache_test_results" not in environment["BAZEL_EXTRA_ARGS"]
    assert json.loads((output / "execution.json").read_text())["exit_code"] == code


def test_native_process_group_is_bounded():
    assert (
        baseline.run_native(
            [sys.executable, "-c", "import time; time.sleep(30)"], {}, 0.05
        )
        == 124
    )
