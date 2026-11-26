import base64
import io
import json
import stat
import sys
import threading
import zipfile
from datetime import UTC, datetime

import pytest
from test_bazel_bundle import capture  # noqa: F401 -- shared pytest fixture

from smartci.bazel import transport
from smartci.bazel.bundle import canonical, load, pack, sha256
from smartci.bazel.collection import CaptureCommand, CaptureConfig
from smartci.bazel.transport import Publisher, fetch, unpack
from smartci.cli import main

NOW = datetime(2026, 11, 26, tzinfo=UTC).timestamp()


@pytest.fixture
def publisher(tmp_path, request):
    _, revision, profile, artifacts = request.getfixturevalue("capture")
    config = CaptureConfig(
        schema_version="1",
        profile=profile,
        native=CaptureCommand(argv=["/usr/bin/native"], timeout_seconds=60),
        query=CaptureCommand(argv=["/usr/bin/query"], timeout_seconds=60),
    )
    config_digest = sha256(canonical(config.model_dump()))
    bundle = pack(
        tmp_path / "producer",
        profile,
        revision,
        artifacts,
        capture_config_digest=config_digest,
    )
    policy = Publisher(
        repository=profile.repository,
        branch="main",
        workflow=".github/workflows/maps.yml",
        workflow_digest=sha256(b"reviewed workflow"),
        artifact_prefix="native-enrollment",
    )
    collection = {
        "schema_version": "smartci.bazel-collection.v1",
        "status": "ready",
        "revision": revision,
        "map_revision": revision,
        "config_digest": config_digest,
        "manifest_digest": bundle.manifest_digest,
        "cache": "not_supplied",
        "native_exit": 0,
        "query_exit": 0,
        "native_test_targets": 2,
        "native_build_only_targets": 1,
        "model_calls": 0,
    }
    members = {
        "enrollment/collection.json": canonical(collection),
        "enrollment/bundle/manifest.json": canonical(
            bundle.manifest.model_dump(exclude_none=True)
        ),
        **{f"enrollment/bundle/{name}": value for name, value in artifacts.items()},
        "enrollment/capture/native.log": b"ignored native diagnostic",
    }
    run = {
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_sha": revision,
        "head_branch": "main",
        "path": policy.workflow,
        "repository": {"full_name": profile.repository},
        "head_repository": {"full_name": profile.repository},
        "id": 42,
        "run_attempt": 2,
    }
    artifact = {
        "name": "native-enrollment-2",
        "id": 72,
        "expired": False,
        "created_at": "2026-11-25T22:00:00Z",
        "expires_at": "2026-11-30T00:00:00Z",
        "workflow_run": {"id": 42, "head_sha": revision, "head_branch": "main"},
    }
    state = {
        "run": run,
        "artifact": artifact,
        "members": members,
        "definition": b"reviewed workflow",
    }
    routes = []

    def api(route):
        routes.append(route)
        if "/contents/" in route:
            return canonical(
                {
                    "encoding": "base64",
                    "type": "file",
                    "content": base64.b64encode(state["definition"]).decode(),
                }
            )
        if "/workflows/" in route:
            return canonical({"workflow_runs": state.get("runs", [run])})
        if route.endswith("/artifacts?per_page=100"):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                for name, content in members.items():
                    zipped.writestr(name, content)
            state["zip"] = archive.getvalue()
            artifact["digest"] = state.get("digest", "sha256:" + sha256(state["zip"]))
            artifact["size_in_bytes"] = state.get("size", len(state["zip"]))
            return canonical({"artifacts": state.get("artifacts", [artifact])})
        if route.endswith("/72/zip"):
            return state["zip"]
        raise AssertionError(route)

    return policy, revision, config, state, api, routes


def perform(tmp_path, publisher):
    policy, revision, config, _, api, _ = publisher
    return fetch(policy, revision, config, tmp_path / "out", request=api, now=NOW)


def test_discovers_authenticated_map_without_a_supplied_run_id(tmp_path, publisher):
    report = perform(tmp_path, publisher)
    policy, revision, config, _, _, routes = publisher
    assert report["status"] == "ready" and report["run_id"] == 42
    assert report["run_attempt"] == 2 and report["artifact_id"] == 72
    assert report["revision"] == revision
    bundle = load(tmp_path / "out/bundle", report["manifest_digest"], config.profile)
    assert bundle.native.tests == ("//lib:a_test", "//lib:b_test")
    assert bundle.native.build_only == ("//lib:binary",)
    assert json.loads((tmp_path / "out/fetch.json").read_bytes()) == report
    assert not (tmp_path / "out/capture").exists()
    assert all(route.startswith("repos/" + policy.repository) for route in routes)
    assert f"head_sha={revision}" in routes[1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("event", "pull_request"),
        ("event", "pull_request_target"),
        ("event", "workflow_dispatch"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_sha", "a" * 40),
        ("head_branch", "feature"),
        ("path", ".github/workflows/unreviewed.yml"),
        ("repository", {"full_name": "attacker/project"}),
        ("head_repository", {"full_name": "attacker/project"}),
        ("id", True),
        ("id", -1),
        ("run_attempt", 0),
    ],
)
def test_untrusted_runs_are_never_downloaded(tmp_path, publisher, field, value):
    publisher[3]["run"][field] = value
    with pytest.raises(ValueError):
        perform(tmp_path, publisher)
    assert not any(route.endswith("/zip") for route in publisher[5])
    assert not (tmp_path / "out").exists()


def test_manual_publisher_must_be_explicitly_reviewed(tmp_path, publisher):
    policy, revision, config, state, api, _ = publisher
    state["run"]["event"] = "workflow_dispatch"
    policy = Publisher.model_validate(
        {**policy.model_dump(), "event": "workflow_dispatch"}
    )
    report = fetch(policy, revision, config, tmp_path / "out", request=api, now=NOW)
    assert report["status"] == "ready"


@pytest.mark.parametrize(
    "field,value",
    [
        ("expired", True),
        ("created_at", "2026-11-01T00:00:00Z"),
        ("created_at", "2026-11-27T00:00:00Z"),
        ("created_at", "2026-11-25T22:00:00"),
        ("expires_at", "2026-11-25T22:00:00Z"),
        ("id", True),
        ("id", 0),
        ("name", "native-enrollment-1"),
        ("workflow_run", {"id": 9, "head_sha": "a" * 40, "head_branch": "main"}),
    ],
)
def test_invalid_artifact_metadata_is_rejected(tmp_path, publisher, field, value):
    publisher[3]["artifact"][field] = value
    with pytest.raises(ValueError):
        perform(tmp_path, publisher)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("definition", b"changed publisher"),
        ("digest", "sha256:" + "0" * 64),
        ("size", 0),
        ("size", 100 * 1024 * 1024),
        ("runs", []),
    ],
)
def test_missing_or_substituted_origin_fails_closed(tmp_path, publisher, field, value):
    publisher[3][field] = value
    with pytest.raises(ValueError):
        perform(tmp_path, publisher)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("revision", "a" * 40),
        ("map_revision", "a" * 40),
        ("manifest_digest", "0" * 64),
        ("config_digest", "0" * 64),
        ("native_exit", 1),
        ("query_exit", 1),
        ("native_test_targets", 0),
    ],
)
def test_invalid_collection_receipts_never_publish(tmp_path, publisher, field, value):
    members = publisher[3]["members"]
    name = "enrollment/collection.json"
    report = json.loads(members[name])
    report[field] = value
    members[name] = canonical(report)
    with pytest.raises(ValueError):
        perform(tmp_path, publisher)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "defect", ["member", "manifest", "profile", "commands", "missing", "duplicate"]
)
def test_corrupt_or_incompatible_capture_is_rejected(tmp_path, publisher, defect):
    policy, revision, config, state, api, _ = publisher
    members = state["members"]
    if defect == "member":
        members["enrollment/bundle/query.xml"] += b" "
    elif defect == "manifest":
        members["enrollment/bundle/manifest.json"] += b" "
    elif defect == "missing":
        del members["enrollment/bundle/roots.txt"]
    elif defect == "duplicate":
        state["artifacts"] = [state["artifact"], state["artifact"]]
    else:
        values = config.model_dump()
        if defect == "profile":
            values["profile"]["environment_digest"] = "c" * 64
        else:
            values["native"]["timeout_seconds"] += 1
        config = CaptureConfig.model_validate(values)
    with pytest.raises(ValueError):
        fetch(policy, revision, config, tmp_path / "out", request=api, now=NOW)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "defect",
    ["traversal", "absolute", "symlink", "duplicate", "oversized", "directory-count"],
)
def test_unsafe_archive_entries_are_rejected(tmp_path, publisher, defect, monkeypatch):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in publisher[3]["members"].items():
            archive.writestr(name, content)
        if defect == "traversal":
            archive.writestr("../escape", b"bad")
        elif defect == "absolute":
            archive.writestr("/tmp/escape", b"bad")
        elif defect == "symlink":
            entry = zipfile.ZipInfo("link")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, b"/tmp/escape")
        elif defect == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("enrollment/bundle/query.xml", b"duplicate")
        elif defect == "directory-count":
            for index in range(257):
                archive.writestr(f"extra/{index}", b"")
        else:
            monkeypatch.setattr("smartci.bazel.transport.MAX_EXPANDED", 100)
    with pytest.raises(ValueError):
        unpack(raw.getvalue())


def test_existing_output_is_not_overwritten(tmp_path, publisher):
    (tmp_path / "out").mkdir()
    (tmp_path / "out/keep").write_text("keep")
    with pytest.raises(ValueError):
        perform(tmp_path, publisher)
    assert (tmp_path / "out/keep").read_text() == "keep"
    assert publisher[5] == []


def test_cli_unavailable_service_is_a_miss_not_an_empty_plan(
    tmp_path, publisher, monkeypatch, capsys
):
    policy, revision, config, _, _, _ = publisher
    (tmp_path / "publisher.json").write_bytes(canonical(policy.model_dump()))
    (tmp_path / "config.json").write_bytes(canonical(config.model_dump()))

    def unavailable(*args, **kwargs):
        raise OSError("private diagnostic must not escape")

    monkeypatch.setattr("smartci.bazel.commands.fetch", unavailable)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "bazel",
            "fetch",
            "--publisher",
            str(tmp_path / "publisher.json"),
            "--revision",
            revision,
            "--config",
            str(tmp_path / "config.json"),
            "--output",
            str(tmp_path / "out"),
        ],
    )
    assert main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "miss", "code": "UNTRUSTED_OR_UNAVAILABLE_NATIVE_MAP"}
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("defect", ["timeout", "oversized", "failure", "success"])
def test_api_transport_bounds_output_time_and_credentials(
    tmp_path, monkeypatch, defect
):
    executable = tmp_path / "gh"
    body = {
        "timeout": "import time; time.sleep(30)",
        "oversized": "import time; print('x' * 2048, flush=True); time.sleep(30)",
        "failure": "raise SystemExit(4)",
        "success": "print('{}')",
    }[defect]
    executable.write_text(
        f"#!{sys.executable}\nimport os\n"
        "assert 'OPENAI_API_KEY' not in os.environ\n"
        "assert os.environ['GH_TOKEN'] == 'test-token-not-real'\n" + body + "\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")
    monkeypatch.setenv("GH_TOKEN", "test-token-not-real")
    original_timer = threading.Timer
    monkeypatch.setattr(
        transport.threading,
        "Timer",
        lambda seconds, callback: original_timer(
            0.5 if defect == "timeout" else 5, callback
        ),
    )
    monkeypatch.setattr(transport, "MAX_METADATA", 1024)
    if defect == "success":
        assert transport.api("repos/example/project/metadata") == b"{}\n"
    else:
        with pytest.raises(ValueError):
            transport.api("repos/example/project/metadata")


def test_validated_reuse_preserves_original_map_revision(tmp_path, publisher):
    policy, revision, config, state, api, _ = publisher
    newer = "f" * 40
    state["run"]["head_sha"] = newer
    state["artifact"]["workflow_run"]["head_sha"] = newer
    name = "enrollment/collection.json"
    receipt = json.loads(state["members"][name])
    receipt.update(revision=newer, cache="reused", native_exit=None, query_exit=None)
    state["members"][name] = canonical(receipt)
    result = fetch(policy, newer, config, tmp_path / "out", request=api, now=NOW)
    assert result["revision"] == newer and result["map_revision"] == revision


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "example/../evil"),
        ("branch", "main?bad=true"),
        ("workflow", ".github/workflows/../../evil"),
        ("event", "pull_request"),
        ("max_age_seconds", 604801),
        ("artifact_prefix", "prefix/../../../"),
    ],
)
def test_publisher_policy_constrains_api_inputs(publisher, field, value):
    with pytest.raises(ValueError):
        Publisher.model_validate({**publisher[0].model_dump(), field: value})


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError):
        transport.parse_object(b'{"status":"failed","status":"ready"}')


def test_oversized_required_member_is_rejected(publisher, monkeypatch):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in publisher[3]["members"].items():
            archive.writestr(name, content)
    monkeypatch.setitem(transport.MEMBERS, "enrollment/bundle/query.xml", 10)
    with pytest.raises(ValueError):
        unpack(raw.getvalue())
