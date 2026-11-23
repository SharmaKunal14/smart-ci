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
    configured = {"targetConfigured": {"label": "//lib:test"}}
    built = {"targetCompleted": {"label": "//lib:test"}}
    summary = {"testSummary": {"label": "//lib:test"}}
    rows = [
        {
            "id": {"started": {}},
            "started": {"command": "test"},
            "children": [configured, {"buildFinished": {}}, {"buildToolLogs": {}}],
        },
        {"id": configured, "configured": {"testSize": "SMALL"}, "children": [built]},
        {
            "id": built,
            "completed": {"success": True},
            "children": [summary],
        },
        {
            "id": summary,
            "testSummary": {"overallStatus": status},
        },
        {"id": {"buildFinished": {}}, "finished": {"exitCode": {"code": code}}},
    ]
    if complete:
        rows.append({"id": {"buildToolLogs": {}}, "lastMessage": True})
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_bazel_summary_preserves_native_failed_target(tmp_path):
    path = tmp_path / "events.json"
    events(path, "FAILED", 3)
    result = baseline.summarize_events(path)
    assert result["test_target_count"] == 1
    assert result["test_targets"] == {"//lib:test": "FAILED"}
    assert result["exit_code"] == 3
    assert result["build_target_configuration_count"] == 1


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


@pytest.mark.parametrize(
    "defect",
    [
        "missing_announced_test",
        "missing_build_only_target",
        "unannounced_result",
        "aborted_target",
        "events_after_terminal",
        "wrong_command",
        "duplicate_key",
        "false_success_test",
        "false_success_build",
    ],
)
def test_completion_marker_cannot_hide_missing_or_contradictory_evidence(
    tmp_path, defect
):
    path = tmp_path / "events.json"
    events(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    other = {"targetCompleted": {"label": "//lib:build_only"}}
    if defect == "missing_announced_test":
        rows[2]["children"].append({"testSummary": {"label": "//lib:missing"}})
    elif defect == "missing_build_only_target":
        rows[0]["children"].append(other)
    elif defect == "unannounced_result":
        rows.insert(-1, {"id": other, "completed": {"success": True}})
    elif defect == "aborted_target":
        rows[2].pop("completed")
        rows[2]["aborted"] = {"reason": "USER_INTERRUPTED"}
    elif defect == "events_after_terminal":
        rows.append({"id": other, "completed": {"success": True}})
    elif defect == "wrong_command":
        rows[0]["started"]["command"] = "build"
    elif defect == "false_success_test":
        rows[3]["testSummary"]["overallStatus"] = "FAILED"
    elif defect == "false_success_build":
        rows[2]["completed"]["success"] = False
    path.write_text("\n".join(json.dumps(row) for row in rows))
    if defect == "duplicate_key":
        path.write_text(path.read_text().replace('"code": 0', '"code": 3, "code": 0'))
    with pytest.raises(ValueError):
        baseline.summarize_events(path)


def test_build_only_failures_remain_visible(tmp_path):
    path = tmp_path / "events.json"
    events(path, code=1)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    build = {"targetCompleted": {"label": "//bin:application"}}
    rows[0]["children"].append(build)
    rows.insert(-1, {"id": build, "completed": {}})
    path.write_text("\n".join(json.dumps(row) for row in rows))
    result = baseline.summarize_events(path)
    assert result["test_targets"] == {"//lib:test": "PASSED"}
    assert result["failed_build_target_configuration_count"] == 1
    assert result["exit_code"] == 1


def test_large_native_exclusion_id_still_requires_complete_announced_graph(tmp_path):
    path = tmp_path / "events.json"
    events(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    pattern = {
        "pattern": {
            "pattern": [
                "...",
                *[f"-//long_package_name:target_{i}_test" for i in range(250)],
            ]
        }
    }
    assert 4096 < len(json.dumps(pattern)) < 64 * 1024
    rows[0]["children"].append(pattern)
    rows.insert(1, {"id": pattern, "expanded": {}})
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert baseline.summarize_events(path)["complete_stream"] is True
    del rows[1]
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="incomplete"):
        baseline.summarize_events(path)


@pytest.mark.parametrize(
    "defect", ["other_id", "count", "size", "element", "duplicates", "fields"]
)
def test_large_event_ids_reject_unknown_or_unbounded_forms(defect):
    patterns = ["...", *[f"-//long_package_name:target_{i}_test" for i in range(250)]]
    value = {"pattern": {"pattern": patterns}}
    if defect == "other_id":
        value = {"targetCompleted": {"label": "x" * 5000}}
    elif defect == "count":
        patterns.extend(f"-//pkg:test_{i}" for i in range(2048))
    elif defect == "size":
        patterns.extend(f"-//pkg:{'x' * 900}_{i}" for i in range(100))
    elif defect == "element":
        patterns[-1] = {"untrusted": "nested"}
    elif defect == "duplicates":
        patterns[-1] = patterns[1]
    else:
        value["pattern"]["unexpected"] = True
    with pytest.raises(ValueError):
        baseline.event_key(value)


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


def test_failed_container_cleanup_is_reported(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "evidence"
    monkeypatch.chdir(root)
    monkeypatch.setattr(baseline, "run_native", lambda *args: 124)

    def cleanup(command, **kwargs):
        assert command[:3] == ["docker", "rm", "--force"]
        assert command[3].startswith("smartci-baseline-")
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 20
        raise baseline.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(baseline.subprocess, "run", cleanup)
    monkeypatch.setattr(sys, "argv", ["baseline", "--output", str(output)])
    assert baseline.main() == 124
    report = json.loads((output / "execution.json").read_text())
    assert report["evidence_error"] == "NATIVE_TIMEOUT_CONTAINER_CLEANUP_FAILED"
