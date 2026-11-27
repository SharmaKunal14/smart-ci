"""Exercise Action trust boundaries and native failure propagation without a model."""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from test_bazel_bundle import capture, git  # noqa: F401
from test_bazel_execution import execution_case  # noqa: F401

from smartci import action_control as control
from smartci import github_action as delivery
from smartci.bazel.collection import CaptureConfig

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "action_bootstrap", ROOT / "action/bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.fixture
def action_case(tmp_path, request):
    repo, _, _, config, _, _, _ = request.getfixturevalue("execution_case")
    execution = config()
    policy = {
        "schema_version": "1",
        "files": [".smartci/adapter.py"],
        "capture": CaptureConfig(
            schema_version="1",
            profile=execution.profile,
            native=execution.full,
            query=execution.full,
        ).model_dump(),
        "execution": execution.model_dump(),
        "fallback": {
            "argv": [sys.executable, "{control}/.smartci/adapter.py", "{capture}"],
            "timeout_seconds": 10,
        },
    }
    folder = repo / ".smartci"
    folder.mkdir()
    (folder / "native.json").write_text(json.dumps(policy))
    (folder / "adapter.py").write_text(
        "import os,sys\nfrom pathlib import Path\nassert 'GH_TOKEN' not in os.environ and 'OPENAI_API_KEY' not in os.environ\nPath(sys.argv[1], 'called').write_text('reviewed full')\nraise SystemExit(7)\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "reviewed Action configuration")
    base = git(repo, "rev-parse", "HEAD")
    (folder / "adapter.py").write_text(
        "raise SystemExit('PR adapter must not execute')\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "untrusted PR change")
    head = git(repo, "rev-parse", "HEAD")
    repository = execution.profile.repository
    event = tmp_path / "event.json"
    payload = {
        "repository": {"full_name": repository},
        "pull_request": {
            "base": {"sha": base, "repo": {"full_name": repository}},
            "head": {"sha": head, "repo": {"full_name": repository}},
        },
    }
    event.write_text(json.dumps(payload))
    return repo, base, head, repository, event, policy


def staged(tmp_path, case):
    repo, _, _, repository, event, _ = case
    value = control.context(repo, event, repository, "pull_request")
    state = tmp_path / "state"
    policy = control.prepare(value, ".smartci/native.json", state)
    return value, state, policy


def test_base_control_files_and_independent_fallback_preserve_failure(
    tmp_path, action_case, monkeypatch
):
    value, state, policy = staged(tmp_path, action_case)
    assert "reviewed full" in (state / "control/.smartci/adapter.py").read_text()
    assert "PR adapter" not in (state / "control/.smartci/adapter.py").read_text()
    monkeypatch.setenv("GH_TOKEN", "must-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    assert control.full_fallback(value, policy, state) == 7
    assert (state / "installation-fallback/called").read_text() == "reviewed full"
    assert json.loads((state / "fallback.json").read_text())["exit_code"] == 7


@pytest.mark.parametrize(
    "event_name", ["pull_request_target", "push", "workflow_dispatch"]
)
def test_privileged_or_unimplemented_events_are_rejected(action_case, event_name):
    repo, _, _, repository, event, _ = action_case
    with pytest.raises(ValueError, match="pull_request"):
        control.context(repo, event, repository, event_name)


@pytest.mark.parametrize(
    "problem", ["wrong-head", "wrong-repository", "dirty", "injected-revision"]
)
def test_wrong_context_cannot_run_native_code(action_case, problem):
    repo, base, _, repository, event, _ = action_case
    data = json.loads(event.read_text())
    if problem == "wrong-head":
        data["pull_request"]["head"]["sha"] = base
    elif problem == "wrong-repository":
        data["pull_request"]["base"]["repo"]["full_name"] = "another/repository"
    elif problem == "dirty":
        (repo / "untracked").write_text("dirty")
    else:
        data["pull_request"]["base"]["sha"] = "--exec=untrusted"
    event.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        control.context(repo, event, repository, "pull_request")


@pytest.mark.parametrize(
    "path", ["../escape", "/etc/passwd", ".git/config", "x/../y", "x\\y", "x\ny"]
)
def test_control_path_traversal_is_rejected(path):
    with pytest.raises(ValueError):
        control.relative(path)


def test_symlink_and_duplicate_policy_are_rejected(tmp_path, action_case):
    repo, _, _, repository, event, _ = action_case
    policy_file = repo / ".smartci/native.json"
    policy_file.unlink()
    policy_file.symlink_to("adapter.py")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "symlink control")
    commit = git(repo, "rev-parse", "HEAD")
    data = json.loads(event.read_text())
    data["pull_request"]["base"]["sha"] = commit
    data["pull_request"]["head"]["sha"] = commit
    event.write_text(json.dumps(data))
    value = control.context(repo, event, repository, "pull_request")
    with pytest.raises(ValueError, match="regular"):
        control.prepare(value, ".smartci/native.json", tmp_path / "symlink-out")
    bad = tmp_path / "duplicate.json"
    bad.write_text('{"schema_version":"1","schema_version":"2"}')
    with pytest.raises(ValueError, match="duplicate"):
        control.read_object(bad)


def test_release_digest_mismatch_cannot_install_or_execute(tmp_path, monkeypatch):
    action = tmp_path / "action"
    action.mkdir()
    (action / "cli-release.json").write_text(
        json.dumps(
            {
                "tag": "cli-v0.2.0a1",
                "wheel": "smartci-0.2.0a1-py3-none-any.whl",
                "sha256": "0" * 64,
            }
        )
    )
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "state_root", lambda: state)

    class Downloader:
        def open(self, *args, **kwargs):
            return io.BytesIO(b"corrupted wheel")

    monkeypatch.setattr(
        bootstrap.urllib.request, "build_opener", lambda *args: Downloader()
    )
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unverified release executed"),
    )
    with pytest.raises(ValueError, match="integrity"):
        bootstrap.install()
    assert not (state / "installation.json").exists()


def test_cli_force_full_bypasses_reconstruction_and_preserves_bep(
    tmp_path, action_case, monkeypatch
):
    _, state, _ = staged(tmp_path, action_case)
    delivery.prepare(state)
    monkeypatch.setattr(
        "smartci.bazel.lifecycle.collect",
        lambda *args: pytest.fail("forced-full must not enroll"),
    )
    assert delivery.execute(state, force_full=True) == 0
    execution = control.read_object(state / "native-pr/execution/execution.json")
    assert execution["status"] == "passed" and execution["mode"] == "full"
    assert execution["bazel"]["test_target_count"] == 2
    assert control.read_object(state / "native-pr/lifecycle.json") == {
        "map": "bypassed",
        "rebuild": None,
    }


def test_publisher_failure_is_recoverable_but_repository_mismatch_is_not(
    tmp_path, action_case, monkeypatch
):
    _, state, policy = staged(tmp_path, action_case)
    policy["publisher"] = {
        "schema_version": "1",
        "repository": action_case[3],
        "branch": "main",
        "workflow": ".github/workflows/map.yml",
        "workflow_digest": "0" * 64,
        "artifact_prefix": "native-enrollment",
    }
    policy["publisher_capture"] = policy["capture"]
    (state / "policy.json").write_text(json.dumps(policy))

    def unavailable(_):
        raise ValueError("unavailable")

    monkeypatch.setattr(delivery, "api", unavailable)
    delivery.prepare(state)
    assert control.read_object(state / "fetch-error.json")["status"] == "unavailable"
    policy["execution"]["profile"]["repository"] = "wrong/repository"
    (state / "policy.json").write_text(json.dumps(policy))
    with pytest.raises(ValueError, match="profiles differ"):
        delivery.load(state)


def test_bootstrap_executes_reviewed_full_when_cli_not_ready(
    tmp_path, action_case, monkeypatch
):
    _, state, _ = staged(tmp_path, action_case)
    monkeypatch.setattr(bootstrap, "state_root", lambda: state)
    monkeypatch.setenv("CLI_READY", "false")
    assert bootstrap.execute() == 7


def test_bootstrap_does_not_hide_installed_cli_failure(
    tmp_path, action_case, monkeypatch
):
    _, state, _ = staged(tmp_path, action_case)
    monkeypatch.setattr(bootstrap, "state_root", lambda: state)
    monkeypatch.setenv("CLI_READY", "true")
    monkeypatch.setenv("GH_TOKEN", "not-for-native-code")

    def invoke(argv, **kwargs):
        assert argv[1:4] == ["-I", "-m", "smartci.cli"]
        assert "GH_TOKEN" not in kwargs["env"]
        return type("Result", (), {"returncode": 7})()

    monkeypatch.setattr(bootstrap.subprocess, "run", invoke)
    assert bootstrap.execute() == 7
    assert not (state / "installation-fallback").exists()


def test_summary_records_fallback_without_turning_failure_green(
    tmp_path, action_case, monkeypatch
):
    value, state, policy = staged(tmp_path, action_case)
    control.full_fallback(value, policy, state)
    monkeypatch.setattr(bootstrap, "state_root", lambda: state)
    output, summary = tmp_path / "outputs", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    bootstrap.summary()
    assert "mode=full\nstatus=failed\n" in output.read_text()
    assert "independent full native command" in summary.read_text()


def test_bundled_profile_is_base_owned_and_rejects_command_overrides(
    tmp_path, action_case
):
    repo, _, _, repository, event, _ = action_case
    minimal = {"schema_version": "1", "profile": "abseil-gcc-cpp17-v1"}
    configuration = repo / ".smartci/native.json"
    configuration.write_text(json.dumps(minimal))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "reviewed preset")
    commit = git(repo, "rev-parse", "HEAD")
    payload = json.loads(event.read_text())
    payload["pull_request"]["base"]["sha"] = commit
    payload["pull_request"]["head"]["sha"] = commit
    event.write_text(json.dumps(payload))
    value = control.context(repo, event, repository, "pull_request")
    policy = control.prepare(value, ".smartci/native.json", tmp_path / "preset", ROOT)
    parsed = delivery.ActionPolicy.model_validate(policy)
    assert parsed.capture.profile.repository == repository
    assert parsed.execution.profile == parsed.capture.profile
    assert parsed.files == []
    assert parsed.publisher is None
    assert parsed.capture.native.argv[2] == str(
        ROOT / "examples/abseil/collection_driver.py"
    )
    assert parsed.fallback.argv[-1] == "{capture}/full"
    minimal["fallback"] = {"argv": ["/bin/true"], "timeout_seconds": 10}
    configuration.write_text(json.dumps(minimal))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "unsupported preset override")
    value["base"] = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="unsupported native profile"):
        control.prepare(value, ".smartci/native.json", tmp_path / "bad-preset", ROOT)
