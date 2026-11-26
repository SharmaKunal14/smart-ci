import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_observation_comparison import pair, resign, write  # noqa: F401


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "examples/textual"))
    return importlib.import_module("runtime_candidate"), importlib.import_module(
        "compare_candidate"
    )


@pytest.fixture
def experiment(pair, modules):  # noqa: F811 - imported pytest fixture
    runner, comparator = modules
    seed = pair
    run = json.loads((seed / "run.json").read_text())
    run.update(
        repository={"full_name": runner.REPOSITORY},
        head_repository={"full_name": runner.REPOSITORY},
        path=".github/workflows/smartci-pilot.yml",
        head_branch="codex/runtime-candidate-enrollment",
        conclusion="success",
        updated_at="2026-11-22T10:00:13Z",
    )
    write(seed / "run.json", run)
    jobs = json.loads((seed / "jobs.json").read_text())
    for job in jobs["jobs"]:
        job["conclusion"] = "success"
    write(seed / "jobs.json", jobs)
    xml = b'<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="tests.test_app" name="regression"/><testcase classname="tests.test_other" name="other"/></testsuite></testsuites>'
    profile = {"packages": [["pytest", "9"]]}
    for mode in ("native", "observe-scoped"):
        folder = seed / f"textual-{mode}-1"
        execution = json.loads((folder / "execution.json").read_text())
        execution["exit_code"] = 0
        write(folder / "execution.json", execution)
        write(folder / "profile.json", profile)
        (folder / "junit.xml").write_bytes(xml)
    observation = json.loads(
        (seed / "textual-observe-scoped-1/observation.json").read_text()
    )
    observation.update(exit_code=0, case_count=2)
    resign(observation)
    write(seed / "textual-observe-scoped-1/observation.json", observation)
    root = seed / "candidate-run"
    root.mkdir()
    run.update(head_sha="c" * 40, head_branch="candidate", conclusion="failure")
    write(root / "run.json", run)
    jobs["jobs"][1]["name"] = "candidate"
    for job in jobs["jobs"]:
        job["conclusion"] = "failure"
    write(root / "jobs.json", jobs)
    for mode in ("native", "candidate"):
        folder = root / f"textual-{mode}-1"
        folder.mkdir()
        write(
            folder / "execution.json",
            {
                "base": "b" * 40,
                "head": "c" * 40,
                "mode": mode,
                "execution": "full" if mode == "native" else "subset",
                "targets": None if mode == "native" else ["tests/test_app.py"],
                "planning_error": None,
                "exit_code": 1,
                "required_execution": "full",
                "omission_authorized": False,
                "harness_sha256": "f" * 64,
            },
        )
        write(folder / "profile.json", profile)
        data = xml.replace(b'failures="0"', b'failures="1"').replace(
            b'name="regression"/>',
            b'name="regression"><failure>bug</failure></testcase>',
        )
        if mode == "candidate":
            data = data.replace(b'tests="2"', b'tests="1"').replace(
                b'<testcase classname="tests.test_other" name="other"/>', b""
            )
        (folder / "junit.xml").write_bytes(data)
    candidate = {
        "schema_version": "smartci.runtime-shadow-candidate.v1",
        "comparison": {"base": "b" * 40, "head": "c" * 40},
        "observation_digest": observation["digest"],
        "required_execution": "full",
        "omission_authorized": False,
        "candidate_files": ["tests/test_app.py"],
        "fallback": [],
    }
    resign(candidate)
    write(root / "textual-candidate-1/candidate.json", candidate)
    return root, seed, runner, comparator


def test_pair_accounts_for_full_failures_and_does_not_claim_production_savings(
    experiment,
):
    root, seed, _, comparator = experiment
    report = comparator.compare(root, seed)
    assert report["jobs"]["native"]["cases"] == 2
    assert report["jobs"]["candidate"]["cases"] == 1
    assert report["comparison"]["identical_selected_outcomes_and_no_missed_failures"]
    assert report["comparison"]["candidate_feedback_seconds_saved"] == -2
    assert not report["comparison"]["production_selective_savings_demonstrated"]


def test_omitted_native_failure_is_reported_even_when_candidate_catches_another(
    experiment,
):
    root, seed, _, comparator = experiment
    path = root / "textual-native-1/junit.xml"
    path.write_bytes(
        path.read_bytes()
        .replace(b'failures="1"', b'failures="2"')
        .replace(
            b'name="other"/>', b'name="other"><failure>missed bug</failure></testcase>'
        )
    )
    result = comparator.compare(root, seed)["comparison"]
    assert result["missed_native_failures"] == ["tests.test_other::other"]
    assert not result["identical_selected_outcomes_and_no_missed_failures"]


@pytest.mark.parametrize(
    "defect",
    [
        "seed_revision",
        "seed_origin",
        "seed_failed",
        "profile",
        "head",
        "digest",
        "unauthorized",
        "missing_full",
    ],
)
def test_stale_incomplete_and_misbound_evidence_cannot_validate(experiment, defect):
    root, seed, _, comparator = experiment
    path, key, value = {
        "seed_revision": (seed / "run.json", "head_sha", "d" * 40),
        "seed_origin": (
            seed / "run.json",
            "repository",
            {"full_name": "different/repo"},
        ),
        "seed_failed": (seed / "run.json", "conclusion", "failure"),
        "profile": (root / "textual-candidate-1/profile.json", "packages", []),
        "head": (root / "textual-candidate-1/execution.json", "head", "d" * 40),
        "digest": (root / "textual-candidate-1/candidate.json", "digest", "0" * 64),
        "unauthorized": (
            root / "textual-candidate-1/execution.json",
            "omission_authorized",
            True,
        ),
        "missing_full": (
            root / "textual-native-1/execution.json",
            "execution",
            "subset",
        ),
    }[defect]
    data = json.loads(path.read_text())
    data[key] = value
    write(path, data)
    with pytest.raises(ValueError):
        comparator.compare(root, seed)


def test_missing_map_executes_native_full_command_and_preserves_failure(
    tmp_path, monkeypatch, modules
):
    runner, _ = modules
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "results"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--mode" in command:
            raise subprocess.CalledProcessError(2, command)
        return SimpleNamespace(returncode=1 if "pytest" in command else 0)

    monkeypatch.chdir(root)
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: b"b" * 40)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "pilot",
            "--mode",
            "candidate",
            "--base",
            "a" * 40,
            "--head",
            "b" * 40,
            "--output",
            str(output),
            "--enrollment",
            str(tmp_path / "missing"),
            "--planner-python",
            "python",
        ],
    )
    assert runner.main() == 1
    command = next(c for c in calls if "pytest" in c)
    assert command[3:5] == ["tests", "-v"]
    assert "--cov=./src/textual" in command
    execution = json.loads((output / "execution.json").read_text())
    assert execution["execution"] == "full"
    assert execution["planning_error"] == "CalledProcessError"
