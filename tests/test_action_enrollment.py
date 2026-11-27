"""Automatic map publication must remain separate from untrusted PR execution."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_bazel_bundle import capture, git  # noqa: F401
from test_bazel_collection import collector  # noqa: F401
from test_bazel_execution import execution_case  # noqa: F401
from test_github_action import action_case, bootstrap  # noqa: F401

from smartci import action_control as control
from smartci import github_action as delivery
from smartci.bazel.bundle import canonical, load
from smartci.bazel.execution import ExecutionConfig

WORKFLOW = ".github/workflows/maps.yml"


@pytest.fixture
def enrollment_case(tmp_path, request):
    repo, _, configuration, inputs = request.getfixturevalue("collector")

    def build(defect="none"):
        capture_config = configuration(defect)
        execution = ExecutionConfig(
            schema_version="1",
            profile=capture_config.profile,
            full=capture_config.native,
            subset=capture_config.native,
            subset_options_digest="a" * 64,
        )
        policy = {
            "schema_version": "1",
            "files": [],
            "capture": capture_config.model_dump(),
            "execution": execution.model_dump(),
            "fallback": capture_config.native.model_dump(),
            "maps": {"branch": "main", "workflow": WORKFLOW},
        }
        workflow = repo / WORKFLOW
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("name: reviewed map producer\n")
        (repo / ".smartci").mkdir(exist_ok=True)
        (repo / ".smartci/native.json").write_text(json.dumps(policy))
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "reviewed enrollment")
        head = git(repo, "rev-parse", "HEAD")
        repository = capture_config.profile.repository
        event = tmp_path / "push.json"
        event.write_text(
            json.dumps(
                {
                    "repository": {"full_name": repository},
                    "after": head,
                    "ref": "refs/heads/main",
                    "deleted": False,
                }
            )
        )
        environment = {
            "workflow_ref": f"{repository}/{WORKFLOW}@refs/heads/main",
            "workflow_sha": head,
            "ref": "refs/heads/main",
            "sha": head,
        }
        value, invocation = control.invocation_context(
            repo, event, repository, "push", **environment
        )
        state = tmp_path / "state"
        control.prepare(value, ".smartci/native.json", state, invocation=invocation)
        return repo, state, value, event, environment, inputs, capture_config

    return build


def test_approved_push_enrolls_native_scope_and_publishes_only_validated_map(
    enrollment_case, monkeypatch
):
    _, state, value, _, _, inputs, config = enrollment_case()
    monkeypatch.setattr(
        delivery, "api", lambda *_: pytest.fail("push must not retrieve PR maps")
    )
    monkeypatch.setenv("GH_TOKEN", "never-native")
    monkeypatch.setenv("OPENAI_API_KEY", "never-native")
    delivery.prepare(state)
    assert delivery.execute(state) == 0
    publication = control.read_object(state / "publication.json")
    report = control.read_object(state / "enrollment/collection.json")
    assert publication["revision"] == value["head"]
    assert publication["manifest_digest"] == report["manifest_digest"]
    assert publication["model_calls"] == 0
    assert (inputs / "native.called").exists() and (inputs / "query.called").exists()
    bundle = load(
        state / "enrollment/bundle", publication["manifest_digest"], config.profile
    )
    assert len(bundle.native.tests) == 2 and len(bundle.native.build_only) == 1
    assert not (state / "native-pr").exists()


@pytest.mark.parametrize(
    "defect", ["native-fail", "query-fail", "tamper", "missing", "version"]
)
def test_failed_enrollment_cannot_emit_publication(enrollment_case, defect):
    _, state, _, _, _, _, _ = enrollment_case(defect)
    delivery.prepare(state)
    assert delivery.execute(state) != 0
    assert (
        control.read_object(state / "enrollment/collection.json")["status"] == "failed"
    )
    assert not (state / "publication.json").exists()
    assert not (state / "enrollment/bundle/manifest.json").exists()


@pytest.mark.parametrize(
    "problem",
    [
        "repository",
        "deleted",
        "tag",
        "sha",
        "workflow-sha",
        "workflow-repository",
        "workflow-ref",
        "checkout",
        "event",
    ],
)
def test_push_event_identity_must_match_exact_checkout(enrollment_case, problem):
    repo, _, value, event, environment, _, _ = enrollment_case()
    payload = control.read_object(event)
    event_name = "push"
    if problem == "repository":
        payload["repository"] = {"full_name": "attacker/repo"}
    elif problem == "deleted":
        payload["deleted"] = True
    elif problem == "tag":
        payload["ref"] = environment["ref"] = "refs/tags/main"
    elif problem == "sha":
        environment["sha"] = "b" * 40
    elif problem == "workflow-sha":
        environment["workflow_sha"] = "b" * 40
    elif problem == "workflow-repository":
        environment["workflow_ref"] = f"attacker/repo/{WORKFLOW}@refs/heads/main"
    elif problem == "workflow-ref":
        environment["workflow_ref"] = environment["workflow_ref"].replace(
            "heads/main", "heads/other"
        )
    elif problem == "checkout":
        (repo / "untracked").write_text("dirty")
    else:
        event_name = "pull_request_target"
    event.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        control.invocation_context(
            repo, event, value["repository"], event_name, **environment
        )


@pytest.mark.parametrize("problem", ["branch", "workflow", "no-map", "mixed-publisher"])
def test_policy_cannot_enroll_an_unapproved_push(tmp_path, enrollment_case, problem):
    repo, _, value, _, _, _, _ = enrollment_case()
    policy = control.read_object(repo / ".smartci/native.json")
    if problem == "branch":
        policy["maps"]["branch"] = "another"
    elif problem == "workflow":
        policy["maps"]["workflow"] = ".github/workflows/another.yml"
    elif problem == "no-map":
        del policy["maps"]
    else:
        policy["publisher"] = {"branch": "another"}
    (repo / ".smartci/native.json").write_text(json.dumps(policy))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "unapproved policy")
    value["base"] = value["head"] = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError):
        control.prepare(
            value,
            ".smartci/native.json",
            tmp_path / "rejected",
            invocation={"event": "push", "branch": "main", "workflow": WORKFLOW},
        )
    assert not (tmp_path / "rejected").exists()


def test_pr_uses_base_workflow_and_cannot_publish(
    tmp_path, enrollment_case, monkeypatch
):
    repo, _, value, _, _, _, config = enrollment_case()
    approved_workflow = (repo / WORKFLOW).read_bytes()
    (repo / WORKFLOW).write_text("name: PR-controlled producer\n")
    policy = control.read_object(repo / ".smartci/native.json")
    policy["maps"]["branch"] = "attacker"
    (repo / ".smartci/native.json").write_text(json.dumps(policy))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "PR cannot approve its publisher")
    value["head"] = git(repo, "rev-parse", "HEAD")
    state = tmp_path / "pr"
    control.prepare(
        value,
        ".smartci/native.json",
        state,
        invocation={"event": "pull_request", "branch": "main", "workflow": WORKFLOW},
    )
    called = []

    def api(route):
        assert route.endswith("/git/ref/heads/main")
        return canonical({"object": {"type": "commit", "sha": value["base"]}})

    def fetch(publisher, revision, contract, output):
        called.append(publisher)
        assert revision == value["base"]
        assert (
            publisher.workflow_digest == hashlib.sha256(approved_workflow).hexdigest()
        )
        assert (
            publisher.event == "push"
            and publisher.artifact_prefix == "smartci-native-map"
        )
        assert contract == config

    monkeypatch.setattr(delivery, "api", api)
    monkeypatch.setattr(delivery, "fetch", fetch)
    monkeypatch.setattr(
        delivery, "collect", lambda *_: pytest.fail("PR cannot enroll a publisher")
    )
    delivery.prepare(state)
    assert len(called) == 1
    assert delivery.execute(state, force_full=True) == 0
    assert (
        not (state / "enrollment").exists()
        and not (state / "publication.json").exists()
    )


def test_capture_identity_changes_with_copied_adapter_contents(tmp_path, request):
    repo, _, _, repository, _, original_policy = request.getfixturevalue("action_case")
    policy = copy.deepcopy(original_policy)
    policy["maps"] = {"branch": "main", "workflow": WORKFLOW}
    policy["capture"]["native"] = policy["fallback"]
    (repo / ".smartci/native.json").write_text(json.dumps(policy))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "automatic map policy")
    value = {
        "repository": repository,
        "repo": str(repo),
        "base": git(repo, "rev-parse", "HEAD"),
        "head": git(repo, "rev-parse", "HEAD"),
    }
    first = control.prepare(value, ".smartci/native.json", tmp_path / "first")
    (repo / ".smartci/adapter.py").write_text("raise SystemExit('changed adapter')\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "changed capture implementation")
    value["base"] = value["head"] = git(repo, "rev-parse", "HEAD")
    second = control.prepare(value, ".smartci/native.json", tmp_path / "second")
    # Ignore state locations; the content-derived subdirectory must differ.
    first_path = Path(first["capture"]["native"]["argv"][1])
    second_path = Path(second["capture"]["native"]["argv"][1])
    assert first_path.relative_to(tmp_path / "first") != second_path.relative_to(
        tmp_path / "second"
    )


@pytest.mark.parametrize(
    "value",
    [
        {"branch": "main", "workflow": WORKFLOW, "artifact_prefix": "x\ninjected=true"},
        {"branch": "--bad", "workflow": WORKFLOW},
        {"branch": "main", "workflow": "../unreviewed.yml"},
        {"branch": "main", "workflow": WORKFLOW, "unknown": True},
    ],
)
def test_map_source_fields_are_bounded(value):
    with pytest.raises(ValueError):
        control.map_source(value)


def test_bootstrap_stages_push_and_failed_install_runs_full_without_publication(
    tmp_path, enrollment_case, monkeypatch
):
    repo, _, value, event, environment, _, _ = enrollment_case()
    runner = tmp_path / "runner"
    runner.mkdir()
    output = tmp_path / "outputs"
    for name, item in {
        "RUNNER_TEMP": str(runner),
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_WORKSPACE": str(repo),
        "GITHUB_REPOSITORY": value["repository"],
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_OUTPUT": str(output),
        "SOURCE_PATH": ".",
        "CONFIG_PATH": ".smartci/native.json",
        "CLI_READY": "false",
        **{f"GITHUB_{name.upper()}": item for name, item in environment.items()},
    }.items():
        monkeypatch.setenv(name, item)
    bootstrap.stage()
    assert "operation=enroll\nmap-prefix=smartci-native-map\n" in output.read_text()
    assert bootstrap.execute() == 0
    state = runner / "smartci-native-action"
    assert control.read_object(state / "fallback.json")["exit_code"] == 0
    assert not (state / "publication.json").exists()
    assert not (state / "enrollment").exists()


@pytest.mark.parametrize("problem", [None, "workflow", "sha", "ref", "branch"])
def test_pr_invocation_validates_merge_workflow_and_head_checkout(request, problem):
    repo, base, head, repository, event, _ = request.getfixturevalue("action_case")
    payload = control.read_object(event)
    payload["pull_request"]["base"]["ref"] = "main"
    if problem == "branch":
        payload["pull_request"]["base"]["ref"] = "main\nother"
    event.write_text(json.dumps(payload))
    environment = {
        "workflow_ref": f"{repository}/{WORKFLOW}@refs/pull/1/merge",
        "workflow_sha": "a" * 40,
        "ref": "refs/pull/1/merge",
        "sha": "a" * 40,
    }
    if problem == "workflow":
        environment["workflow_ref"] = f"{repository}/{WORKFLOW}@refs/heads/main"
    elif problem == "sha":
        environment["workflow_sha"] = "b" * 40
    elif problem == "ref":
        environment["ref"] = "refs/heads/main"
    if problem is not None:
        with pytest.raises(ValueError):
            control.invocation_context(
                repo, event, repository, "pull_request", **environment
            )
    else:
        value, invocation = control.invocation_context(
            repo, event, repository, "pull_request", **environment
        )
        assert value["head"] == head and value["base"] == base
        assert invocation == {
            "event": "pull_request",
            "branch": "main",
            "workflow": WORKFLOW,
        }
