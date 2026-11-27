"""Verify independent cache starts, same-host accounting and failure propagation."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "examples/abseil/matched_trial.py"
SPEC = importlib.util.spec_from_file_location("matched_trial", PATH)
assert SPEC and SPEC.loader
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


@pytest.fixture
def setup_trial(tmp_path, monkeypatch):
    tick = iter(range(1, 100))
    monkeypatch.setattr(
        trial,
        "stamp",
        lambda: {"monotonic_ns": next(tick), "utc": "recorded", "boot_hash": "host-a"},
    )
    (tmp_path / "native-cache-receipt").mkdir()
    trial.write(tmp_path / "native-cache-receipt/cache.json", {"digest": "base"})
    return tmp_path


def arm(root, name, outcome="success", receipt=None):
    trial.begin(root, name)
    # Simulate independently restored base contents, followed by new head work.
    (root / "native-cache/head-output").write_text(name)
    trial.write(
        root / f"matched-evidence/{name}/cache-verified.json",
        receipt if receipt is not None else {"digest": "base"},
    )
    trial.write(
        root / f"matched-evidence/{name}/native-preparation.json",
        {"page_cache_reset": True, "no_active_containers": True},
    )
    trial.finish(root, name, outcome)


@pytest.mark.parametrize("first", ["full", "smart"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_independent_cache_starts_order_and_native_failures(
    setup_trial, first, outcome
):
    root = setup_trial
    branch = f"codex/action-matched-{first}-" + ("1" if first == "full" else "2")
    assert trial.initialize(root, branch) == first
    arm(root, first, outcome)
    assert not (root / "native-cache").exists()
    second = "smart" if first == "full" else "full"
    trial.begin(root, second)
    assert list((root / "native-cache").iterdir()) == []
    trial.write(
        root / f"matched-evidence/{second}/cache-verified.json", {"digest": "base"}
    )
    trial.write(
        root / f"matched-evidence/{second}/native-preparation.json",
        {"page_cache_reset": True, "no_active_containers": True},
    )
    trial.finish(root, second, "success")
    assert trial.verify(root) == (0 if outcome == "success" else 1)
    result = trial.read(root / "matched-evidence/comparison.json")
    assert result["valid_matched_pair"] is True
    assert result["first"] == first
    assert (root / f"native-used-{first}/head-output").read_text() == first


def test_head_cache_cannot_be_reused(setup_trial):
    root = setup_trial
    trial.initialize(root, "codex/action-matched-full-1")
    (root / "native-cache").mkdir()
    with pytest.raises(ValueError, match="absent"):
        trial.begin(root, "full")


def test_second_arm_cannot_start_first(setup_trial):
    root = setup_trial
    trial.initialize(root, "codex/action-matched-full-1")
    with pytest.raises(ValueError, match="first arm"):
        trial.begin(root, "smart")


@pytest.mark.parametrize("problem", ["wrong-cache", "missing-receipt", "wrong-host"])
def test_invalid_measurements_never_pass(setup_trial, problem):
    root = setup_trial
    trial.initialize(root, "codex/action-matched-full-1")
    arm(root, "full")
    arm(root, "smart", receipt={"digest": "head"} if problem == "wrong-cache" else None)
    if problem == "missing-receipt":
        (root / "matched-evidence/smart/cache-verified.json").unlink()
    if problem == "wrong-host":
        path = root / "matched-evidence/smart/start.json"
        data = trial.read(path)
        data["boot_hash"] = "another-host"
        path.write_text(json.dumps(data))
    assert trial.verify(root) == 1
    assert (
        trial.read(root / "matched-evidence/comparison.json")["valid_matched_pair"]
        is False
    )


def test_undeclared_branch_is_rejected(setup_trial):
    with pytest.raises(ValueError, match="declared PR"):
        trial.initialize(setup_trial, "codex/action-matched-extra-5")


def test_matched_policy_preserves_the_reviewed_engine_and_native_profile():
    from smartci.github_action import ActionPolicy

    directory = PATH.parent
    old = ActionPolicy.model_validate_json(
        (directory / "action-warm-policy.json").read_bytes()
    )
    new = ActionPolicy.model_validate_json(
        (directory / "action-matched-policy.json").read_bytes()
    )
    assert new.capture == old.capture
    assert new.execution == old.execution
    assert new.fallback == old.fallback
    assert new.files == old.files == []
    publisher = trial.read(directory / "action-matched-cache-publisher.json")
    assert publisher["branch"] == "codex/action-matched-base"
    assert (
        publisher["workflow_digest"]
        == hashlib.sha256(
            (directory / "action-matched-enroll-workflow.yml").read_bytes()
        ).hexdigest()
    )


def test_pr_workflow_uses_one_vm_read_only_cache_and_base_owned_helper():
    raw = (PATH.parent / "action-matched-workflow.yml").read_text()
    assert raw.count("runs-on:") == 1
    assert "cache-mode: read" in raw and "actions/cache/save@" not in raw
    assert "restore-keys:" not in raw
    assert "base_file(value,'.smartci/matched_trial.py')" in raw
    assert (
        raw.count(
            '/usr/bin/python3 "$GITHUB_WORKSPACE/tool/examples/abseil/baseline.py"'
        )
        == 3
    )
    assert (
        raw.count(
            "uses: SharmaKunal14/smart-ci@e780aeb00eb5b81c35b062c65734067c03279754"
        )
        == 1
    )
    assert 'matched_trial.py" verify' in raw
    assert "Require matched evidence and propagate either native failure" in raw
