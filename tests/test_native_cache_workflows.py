"""Exercise the actual workflow shell's cache-failure execution boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def execution_block(arm):
    raw = (ROOT / f"examples/abseil/cache-pr-{arm}-workflow.yml").read_text()
    name = (
        "Run the independent complete native suite"
        if arm == "control"
        else "Execute the native PR plan or independent full fallback"
    )
    step = raw.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]
    return "\n".join(
        line[10:] for line in step.split("        run: |\n", 1)[1].splitlines()
    )


@pytest.mark.parametrize("arm", ["control", "candidate"])
@pytest.mark.parametrize("verified", ["success", "failure", "skipped"])
@pytest.mark.parametrize("native_exit", [0, 7])
def test_cache_admission_controls_native_path_without_hiding_failures(
    tmp_path, arm, verified, native_exit
):
    workspace = tmp_path / "workspace with spaces"
    scripts = workspace / "tool/examples/abseil"
    scripts.mkdir(parents=True)
    interpreter = workspace / "tool/.venv/bin/python3"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(Path(sys.executable))
    stub = """import json,os,sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv))
raise SystemExit(int(os.environ['NATIVE_EXIT']))
"""
    for name in ["baseline.py", "run_pr.py"]:
        (scripts / name).write_text(stub)
    captured = tmp_path / "captured.json"
    environment = {
        **os.environ,
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(tmp_path),
        "CACHE_VERIFIED": verified,
        "PLANNER_INSTALLED": "success",
        "BASE": "a" * 40,
        "HEAD": "b" * 40,
        "CAPTURE": str(captured),
        "NATIVE_EXIT": str(native_exit),
    }
    result = subprocess.run(
        ["bash", "-e", "-c", execution_block(arm)],
        env=environment,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == native_exit, result.stderr
    argv = json.loads(captured.read_bytes())
    expected = (
        "run_pr.py" if arm == "candidate" and verified == "success" else "baseline.py"
    )
    assert Path(argv[0]).name == expected
    assert ("--native-cache" in argv) == (arm == "control" and verified == "success")
    if arm == "candidate" and verified != "success":
        assert "native-full-fallback" in argv[-1]


def test_missing_planner_runs_native_full_even_when_cache_verified(tmp_path):
    workspace = tmp_path / "workspace"
    scripts = workspace / "tool/examples/abseil"
    scripts.mkdir(parents=True)
    (scripts / "baseline.py").write_text("raise SystemExit(9)\n")
    result = subprocess.run(
        ["bash", "-e", "-c", execution_block("candidate")],
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(workspace),
            "RUNNER_TEMP": str(tmp_path),
            "PLANNER_INSTALLED": "failure",
            "CACHE_VERIFIED": "success",
        },
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 9
