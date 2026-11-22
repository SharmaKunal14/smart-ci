"""The pilot must never turn planning failure into skipped or successful tests."""

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "textual_benchmark",
    Path(__file__).parents[1] / "examples/textual/benchmark.py",
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.parametrize(
    "targets", [[], ["../escape.py"], ["tests/../escape.py"], ["-x"], "tests/test_a.py"]
)
def test_invalid_targets_cannot_be_executed(tmp_path, targets):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(targets))
    with pytest.raises(ValueError):
        benchmark.selected_targets(path)


def test_planning_failure_executes_independent_full_suite_and_keeps_failure(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "output"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--mode" in command:
            raise subprocess.CalledProcessError(2, command)
        return SimpleNamespace(returncode=1 if "pytest" in command else 0)

    monkeypatch.chdir(repo)
    monkeypatch.setattr(benchmark.subprocess, "run", run)
    monkeypatch.setattr(
        benchmark.sys,
        "argv",
        [
            "pilot",
            "--mode",
            "smart",
            "--base",
            "a" * 40,
            "--head",
            "b" * 40,
            "--output",
            str(output),
        ],
    )
    assert benchmark.main() == 1
    command = next(c for c in calls if "pytest" in c)
    assert command[3:5] == ["tests", "-v"]
    assert "--cov=./src/textual" in command
    execution = json.loads((output / "execution.json").read_text())
    assert execution["execution"] == "full"
    assert execution["exit_code"] == 1
    assert ["git", "checkout", "--detach", "b" * 40] in calls


def test_commit_argument_rejects_options():
    with pytest.raises(argparse.ArgumentTypeError):
        benchmark.revision("--upload-pack=bad")


@pytest.mark.parametrize("timeout", [False, True])
def test_observation_runs_full_native_profile_preserves_failure_and_bounds_time(
    tmp_path, monkeypatch, timeout
):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=1)

    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "output"
    monkeypatch.chdir(root)
    monkeypatch.setattr(benchmark.subprocess, "run", run)
    monkeypatch.setattr(
        benchmark.sys,
        "argv",
        [
            "pilot",
            "--mode",
            "observe",
            "--base",
            "a" * 40,
            "--head",
            "b" * 40,
            "--output",
            str(output),
        ],
    )
    assert benchmark.main() == (124 if timeout else 1)
    assert len(calls) == 1
    command, options = calls[0]
    assert command[3:5] == ["tests", "-v"]
    assert "--cov=./src/textual" in command
    assert "smartci.adapters.runtime_observer" in command
    assert options["timeout"] == 900
    report = json.loads((output / "execution.json").read_text())
    assert report["execution"] == "full" and report["planning_seconds"] == 0
