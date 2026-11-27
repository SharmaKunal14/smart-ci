"""Keep the evaluation's published engine, cache admission and full control fixed."""

import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from smartci.github_action import ActionPolicy

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples/abseil"
PIN = "e780aeb00eb5b81c35b062c65734067c03279754"


def execution_block(arm):
    path = EXAMPLES / (
        "action-warm-control-workflow.yml"
        if arm == "full"
        else "action-warm-workflow.yml"
    )
    name = (
        "Run the independent complete native suite"
        if arm == "full"
        else "Run independent cold full fallback when cache admission fails"
    )
    step = path.read_text().split("    - name: " + name + "\n", 1)[1]
    step = step.split("\n    - ", 1)[0]
    run = step.split("\n      run: ", 1)[1]
    return textwrap.dedent(run[2:]) if run.startswith("|\n") else run


def test_same_reviewed_cache_profile_for_enrollment_selection_and_cli_fallback():
    policy = ActionPolicy.model_validate_json(
        (EXAMPLES / "action-warm-policy.json").read_bytes()
    )
    assert policy.capture.profile.model_dump() == json.loads(
        (EXAMPLES / "cache-profile.json").read_bytes()
    )
    assert policy.capture.profile == policy.execution.profile
    assert policy.execution.subset_options_digest == (
        "1295f68dc45a7afa3cc618706f2b9f73d27b91146254716a3dbd0e8459cab0ff"
    )
    for command in (
        policy.capture.native,
        policy.capture.query,
        policy.execution.full,
        policy.execution.subset,
        policy.fallback,
    ):
        assert command.argv[-2:] == [
            "--native-cache",
            "/home/runner/work/_temp/native-cache",
        ]
        assert command.timeout_seconds <= 1380
    assert policy.files == [] and policy.publisher is None


def test_publisher_binds_the_actual_seed_workflow_and_prs_cannot_save_caches():
    workflow = (EXAMPLES / "action-warm-workflow.yml").read_bytes()
    publisher = json.loads((EXAMPLES / "action-warm-cache-publisher.json").read_bytes())
    assert publisher["workflow_digest"] == hashlib.sha256(workflow).hexdigest()
    assert publisher["event"] == "push"
    assert publisher["branch"] == "codex/action-warm-base"
    raw = workflow.decode()
    seed, pr = raw.split("  test:\n", 1)
    assert "cache-mode: write-only" in seed and "cache-mode: read" in pr
    assert "actions/cache/save@" not in pr
    assert "steps.verified.outcome == 'success'" in pr
    assert "steps.verified.outcome != 'success'" in pr
    assert raw.count("uses: SharmaKunal14/smart-ci@" + PIN) == 2
    for name in ("action-warm-workflow.yml", "action-warm-control-workflow.yml"):
        value = (EXAMPLES / name).read_text()
        assert "restore-keys:" not in value
        assert "'true':" not in value
        assert "base_file(value,'.smartci/cache-publisher.json')" in value
        assert "persist-credentials: false" in value


@pytest.mark.parametrize("arm", ["full", "cold-fallback"])
@pytest.mark.parametrize("verified", ["success", "failure", "skipped"])
@pytest.mark.parametrize("native_exit", [0, 7])
def test_evaluation_native_commands_preserve_cache_admission_and_failures(
    tmp_path, arm, verified, native_exit
):
    workspace = tmp_path / "workspace with spaces"
    script = workspace / "tool/examples/abseil/baseline.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv))\n"
        "raise SystemExit(int(os.environ['NATIVE_EXIT']))\n"
    )
    output = tmp_path / "called.json"
    result = subprocess.run(
        ["bash", "-e", "-c", execution_block(arm)],
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(workspace),
            "RUNNER_TEMP": str(tmp_path),
            "CACHE_VERIFIED": verified,
            "CAPTURE": str(output),
            "NATIVE_EXIT": str(native_exit),
        },
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == native_exit, result.stderr
    argv = json.loads(output.read_text())
    assert ("--native-cache" in argv) == (arm == "full" and verified == "success")
    assert "baseline.py" == Path(argv[0]).name
