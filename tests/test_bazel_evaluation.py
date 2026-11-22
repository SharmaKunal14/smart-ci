import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/abseil"))
try:
    SPEC = importlib.util.spec_from_file_location(
        "native_evaluation", ROOT / "examples/abseil/evaluate.py"
    )
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
finally:
    sys.path.pop(0)

RAW = b"#!/bin/bash\n/usr/local/bin/bazel test ... --keep_going --test_tag_filters=-benchmark\n"


def events():
    return {
        "exit_code": 0,
        "test_targets": {"//lib:one_test": "PASSED", "//lib:two_test": "PASSED"},
        "build_target_results": {
            json.dumps(
                {"targetCompleted": {"label": n, "configuration": {"id": "a" * 64}}}
            ): True
            for n in ["//lib:one_test", "//lib:two_test", "//lib:binary"]
        },
    }


@pytest.fixture
def reference(tmp_path, monkeypatch):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "native": {
                    "bazel": {
                        "test_targets": events()["test_targets"],
                        "build_target_configuration_count": 3,
                    }
                },
                "build_only_labels": ["//lib:binary"],
            }
        )
    )
    monkeypatch.setattr(module, "BASELINE", path)
    return path


def test_scope_validation_rejects_missing_builds_unexpected_tests_or_flakiness(
    reference,
):
    module.verify_results(events(), 0, {"mode": "full"})
    for defect in ["build", "test", "flaky", "exit"]:
        value = copy.deepcopy(events())
        if defect == "build":
            del value["build_target_results"][
                next(reversed(value["build_target_results"]))
            ]
        elif defect == "test":
            del value["test_targets"]["//lib:two_test"]
        elif defect == "flaky":
            value["test_targets"]["//lib:one_test"] = "FLAKY"
        else:
            value["exit_code"] = 3
        with pytest.raises(ValueError):
            module.verify_results(value, 0, {"mode": "full"})


def test_selected_scope_preserves_all_non_test_build_results(reference):
    value = events()
    del value["test_targets"]["//lib:two_test"]
    value["build_target_results"] = {
        k: v
        for k, v in value["build_target_results"].items()
        if json.loads(k)["targetCompleted"]["label"] != "//lib:two_test"
    }
    plan = {
        "mode": "subset",
        "selected": ["//lib:one_test"],
        "build_configurations": {
            "//lib:one_test": ["a" * 64],
            "//lib:binary": ["a" * 64],
        },
    }
    module.verify_results(value, 0, plan)
    plan["build_configurations"]["//lib:binary"] = ["b" * 64]
    with pytest.raises(ValueError, match="configurations"):
        module.verify_results(value, 0, plan)


def test_profile_changes_only_target_patterns_and_retains_native_options(monkeypatch):
    monkeypatch.setattr(
        sys.modules["diagnostics"], "PROFILE_SHA256", hashlib.sha256(RAW).hexdigest()
    )
    assert module.selected_profile(RAW, False) == RAW
    selected = module.selected_profile(RAW, True)
    assert (
        selected.replace(b"--target_pattern_file=/evidence/targets.txt", b"...") == RAW
    )
    subprocess.run(["bash", "-n"], input=selected, check=True)
    with pytest.raises(ValueError):
        module.selected_profile(RAW + b"# drift", True)


@pytest.mark.parametrize("mode", ["native", "candidate"])
def test_missing_evidence_executes_independent_full_command_without_credentials(
    tmp_path, monkeypatch, reference, mode
):
    root = tmp_path / "source"
    root.mkdir()
    output = tmp_path / "result"
    monkeypatch.chdir(root)
    monkeypatch.setattr(module, "verify_checkout", lambda *_: RAW)
    monkeypatch.setattr(
        sys.modules["diagnostics"], "PROFILE_SHA256", hashlib.sha256(RAW).hexdigest()
    )
    monkeypatch.setattr(module, "summarize_events", lambda _: events())
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("GH_TOKEN", "must-not-pass")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-pass")

    def run(profile, directory, environment, timeout):
        assert profile.read_bytes() == RAW
        assert (directory / "targets.txt").read_text() == "...\n"
        assert not any(
            key in environment
            for key in ("OPENAI_API_KEY", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY")
        )
        assert timeout == 1200
        return 0, 1.0, None

    monkeypatch.setattr(module, "run_profile", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--mode",
            mode,
            "--base",
            "a" * 40,
            "--head",
            "b" * 40,
            "--output",
            str(output),
        ],
    )
    assert module.main() == 0
    result = json.loads((output / "execution.json").read_text())
    assert result["evidence_error"] is None
    assert result["production_omission_authorized"] is False
    assert json.loads((output / "plan.json").read_text())["mode"] == "full"


def test_bad_artifact_hash_is_rejected_before_planning(tmp_path, monkeypatch):
    ref = tmp_path / "reference.json"
    ref.write_text(
        json.dumps(
            {
                "upstream": module.UPSTREAM,
                "native_profile_sha256": module.PROFILE_SHA256,
                "artifact_sha256": {"query.xml": "a" * 64},
            }
        )
    )
    monkeypatch.setattr(module, "MAP_REFERENCE", ref)
    (tmp_path / "query.xml").write_text("forged")
    with pytest.raises(ValueError, match="identity mismatch"):
        module.plan_candidate(tmp_path, "a" * 40, "b" * 40, tmp_path)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
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
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci/linux_gcc-latest_libstdcxx_bazel.sh").write_bytes(RAW)
    (tmp_path / "ci/linux_docker_containers.sh").write_text("# pinned image")
    (tmp_path / ".gitignore").write_text("*.ignored\n")
    git("add", ".")
    git("commit", "-qm", "initial")
    head = git("rev-parse", "HEAD")
    monkeypatch.setattr(module, "UPSTREAM", head)
    monkeypatch.setattr(
        sys.modules["diagnostics"], "PROFILE_SHA256", hashlib.sha256(RAW).hexdigest()
    )
    return tmp_path, head, git


def test_checkout_requires_exact_head_clean_inputs_and_pinned_image(checkout):
    root, head, git = checkout
    assert module.verify_checkout(root, head) == RAW
    with pytest.raises(ValueError):
        module.verify_checkout(root, "b" * 40)
    extra = root / "output.ignored"
    extra.write_text("unexpected")
    with pytest.raises(ValueError):
        module.verify_checkout(root, head)
    extra.unlink()
    (root / "ci/linux_docker_containers.sh").write_text("different image")
    with pytest.raises(subprocess.CalledProcessError):
        module.verify_checkout(root, head)
    git("add", ".")
    git("commit", "-qm", "image drift")
    with pytest.raises(ValueError, match="container"):
        module.verify_checkout(root, git("rev-parse", "HEAD"))


def test_paired_workflow_preserves_verified_native_runner_policy():
    native = (ROOT / "examples/abseil/resource-baseline-workflow.yml").read_text()
    paired = (ROOT / "examples/abseil/evaluation-workflow.yml").read_text()
    policy = native[
        native.index("      - name: Bound unused") : native.index(
            "      - name: Run complete"
        )
    ]
    restoration = native[
        native.index("      - name: Restore the Apport") : native.index(
            "      - name: Publish complete"
        )
    ]
    assert policy in paired and restoration in paired
    assert "secrets." not in paired and "pull_request_target" not in paired
    assert "contents: read" in paired and "actions: read" in paired
    assert "fail-fast: false" in paired and "max-parallel: 2" in paired
    assert "timeout-minutes: 25" in paired
    assert 'python3 "$GITHUB_WORKSPACE/tool/examples/abseil/evaluate.py"' in paired
