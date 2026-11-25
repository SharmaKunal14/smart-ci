import json
import os
import subprocess
import sys

import pytest

from smartci.bazel.bundle import Profile, canonical, load, pack, sha256
from smartci.bazel.commands import revision_tree
from smartci.bazel.graph import QueryError
from smartci.bazel.planning import parse_tree
from smartci.cli import main

GRAPH = b"""<query>
<source-file name="//lib:a.h"/><source-file name="//lib:b.h"/>
<rule name="//lib:a_test" class="cc_test"><rule-input name="//lib:a.h"/></rule>
<rule name="//lib:b_test" class="cc_test"><rule-input name="//lib:b.h"/></rule>
<rule name="//lib:binary" class="cc_binary"><rule-input name="//lib:a.h"/></rule>
</query>"""
ROOTS = ["//lib:a_test", "//lib:b_test", "//lib:binary"]


def git(repo, *args):
    return (
        subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.test",
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )
        .decode()
        .strip()
    )


def capture_events():
    pattern = {"pattern": {"pattern": ["..."]}}
    built = [
        {"targetCompleted": {"label": name, "configuration": {"id": "a" * 64}}}
        for name in ROOTS
    ]
    rows = [
        {
            "id": {"started": {}},
            "started": {
                "command": "test",
                "buildToolVersion": "9.1.0",
                "optionsDescription": "--compilation_mode=fastbuild",
                "workspaceDirectory": "/workspace",
                "workingDirectory": "/workspace",
            },
            "children": [pattern, *built, {"buildFinished": {}}, {"buildToolLogs": {}}],
        },
        {"id": pattern, "expanded": {}},
    ]
    for index, name in enumerate(ROOTS):
        summary = {"testSummary": {"label": name}}
        rows.append(
            {
                "id": built[index],
                "completed": {"success": True},
                "children": [summary] if name.endswith("_test") else [],
            }
        )
        if name.endswith("_test"):
            rows.append({"id": summary, "testSummary": {"overallStatus": "PASSED"}})
    rows += [
        {"id": {"buildFinished": {}}, "finished": {"exitCode": {"code": 0}}},
        {"id": {"buildToolLogs": {}}, "lastMessage": True},
    ]
    return rows


@pytest.fixture
def capture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "lib").mkdir()
    for name in ["lib/a.h", "lib/b.h", "lib/BUILD.bazel", "MODULE.bazel"]:
        (repo / name).write_text("initial\n")
    git(repo, "add", ".")
    git(repo, "commit", "--no-gpg-sign", "-qm", "initial")
    revision = git(repo, "rev-parse", "HEAD")
    profile = Profile(
        schema_version="1",
        repository="example/project",
        bazel_version="9.1.0",
        command_digest="a" * 64,
        options_digest=sha256(b"--compilation_mode=fastbuild"),
        environment_digest="b" * 64,
        query_mode="unconfigured-deps-all",
        change_model="reviewed-declared-cpp-inputs-v1",
    )
    artifacts = {
        "anchor.tree": revision_tree(repo, revision),
        "query.xml": GRAPH,
        "roots.txt": ("\n".join(ROOTS) + "\n").encode(),
        "native.bep.json": b"\n".join(
            canonical(row).strip() for row in capture_events()
        ),
    }
    return repo, revision, profile, artifacts


def test_bundle_round_trip_and_deterministic_planning_preserve_build_scope(
    tmp_path, capture
):
    repo, revision, profile, artifacts = capture
    first = pack(tmp_path / "first", profile, revision, artifacts)
    second = pack(tmp_path / "second", profile, revision, artifacts)
    assert first.manifest_digest == second.manifest_digest
    loaded = load(tmp_path / "first", first.manifest_digest, profile)
    (repo / "lib/a.h").write_text("changed\n")
    git(repo, "commit", "--no-gpg-sign", "-qam", "source change")
    head = parse_tree(revision_tree(repo, git(repo, "rev-parse", "HEAD")))
    result = loaded.plan(loaded.anchor, head, execution_mode="selective")
    assert result == loaded.plan(loaded.anchor, head, execution_mode="selective")
    assert result["selected"] == ["//lib:a_test"]
    assert result["build_only"] == ["//lib:binary"]
    assert result["patterns"] == ["...", "-//lib:b_test"]
    assert result["production_omission_authorized"] is True
    assert result["bundle_digest"] == first.manifest_digest
    assert (
        sha256(
            canonical({key: value for key, value in result.items() if key != "digest"})
        )
        == result["digest"]
    )
    head["lib/BUILD.bazel"] = head["lib/a.h"]
    fallback = loaded.plan(loaded.anchor, head, execution_mode="selective")
    assert fallback["mode"] == "full" and fallback["patterns"] == ["..."]
    assert fallback["production_omission_authorized"] is False


@pytest.mark.parametrize(
    "member",
    ["manifest.json", "query.xml", "roots.txt", "native.bep.json", "anchor.tree"],
)
def test_substituted_evidence_is_rejected(tmp_path, capture, member):
    _, revision, profile, artifacts = capture
    directory = tmp_path / "bundle"
    bundle = pack(directory, profile, revision, artifacts)
    path = directory / member
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(QueryError, match="identity"):
        load(directory, bundle.manifest_digest, profile)


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "different/project"),
        ("bazel_version", "9.2.0"),
        ("command_digest", "c" * 64),
        ("options_digest", "c" * 64),
        ("environment_digest", "c" * 64),
    ],
)
def test_other_repository_or_profile_cannot_reuse_bundle(
    tmp_path, capture, field, value
):
    _, revision, profile, artifacts = capture
    directory = tmp_path / "bundle"
    bundle = pack(directory, profile, revision, artifacts)
    changed = Profile.model_validate(profile.model_dump() | {field: value})
    with pytest.raises(QueryError, match="profile"):
        load(directory, bundle.manifest_digest, changed)


@pytest.mark.parametrize(
    "defect",
    [
        "subset",
        "truncated",
        "failed",
        "flaky",
        "version",
        "options",
        "subdirectory",
        "duplicate_json",
    ],
)
def test_invalid_native_reference_cannot_be_packaged(tmp_path, capture, defect):
    _, revision, profile, artifacts = capture
    rows = capture_events()
    if defect == "subset":
        rows[0]["children"][0] = {"pattern": {"pattern": ["//lib:a_test"]}}
        rows[1]["id"] = rows[0]["children"][0]
    elif defect == "truncated":
        rows.pop()
    elif defect in {"failed", "flaky"}:
        rows[3]["testSummary"]["overallStatus"] = (
            "FAILED" if defect == "failed" else "FLAKY"
        )
        rows[-2]["finished"]["exitCode"]["code"] = 3 if defect == "failed" else 0
    elif defect == "version":
        rows[0]["started"]["buildToolVersion"] = "9.2.0"
    elif defect == "options":
        rows[0]["started"]["optionsDescription"] = "--test_tag_filters=omit"
    elif defect == "subdirectory":
        rows[0]["started"]["workingDirectory"] = "/workspace/lib"
    raw = b"\n".join(canonical(row).strip() for row in rows)
    if defect == "duplicate_json":
        raw = raw.replace(b'"code":0', b'"code":3,"code":0')
    bad = artifacts | {"native.bep.json": raw}
    with pytest.raises(ValueError):
        pack(tmp_path / "bundle", profile, revision, bad)
    assert not (tmp_path / "bundle").exists()


def test_manifest_members_cannot_escape_or_overwrite_existing_directory(
    tmp_path, capture
):
    _, revision, profile, artifacts = capture
    with pytest.raises(ValueError):
        pack(tmp_path / "invalid", profile, revision, artifacts | {"../outside": b"x"})
    replaced = dict(artifacts)
    replaced["../outside"] = replaced.pop("query.xml")
    with pytest.raises(ValueError, match="unsupported evidence member"):
        pack(tmp_path / "invalid", profile, revision, replaced)
    directory = tmp_path / "bundle"
    first = pack(directory, profile, revision, artifacts)
    with pytest.raises(FileExistsError):
        pack(directory, profile, revision, artifacts)
    assert load(directory, first.manifest_digest, profile).manifest == first.manifest


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_special_evidence_files_are_rejected_without_reading(tmp_path, capture, kind):
    _, revision, profile, artifacts = capture
    directory = tmp_path / "bundle"
    bundle = pack(directory, profile, revision, artifacts)
    member = directory / "query.xml"
    member.unlink()
    if kind == "symlink":
        outside = tmp_path / "outside.xml"
        outside.write_bytes(artifacts["query.xml"])
        member.symlink_to(outside)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation unavailable")
        os.mkfifo(member)
    with pytest.raises((OSError, QueryError)):
        load(directory, bundle.manifest_digest, profile)


def test_query_sources_must_exist_in_the_anchor_tree(tmp_path, capture):
    _, revision, profile, artifacts = capture
    altered = GRAPH.replace(b"lib:b.h", b"lib:missing.h")
    with pytest.raises(QueryError, match="revision tree"):
        pack(tmp_path / "bundle", profile, revision, artifacts | {"query.xml": altered})


def cli(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["smartci", "bazel", *map(str, args)])
    code = main()
    return code, json.loads(capsys.readouterr().out)


def setup_cli(tmp_path, capture):
    repo, revision, profile, artifacts = capture
    profile_path = tmp_path / "profile.json"
    profile_path.write_bytes(canonical(profile.model_dump()))
    for name in ["query.xml", "roots.txt", "native.bep.json"]:
        (tmp_path / name).write_bytes(artifacts[name])
    return repo, revision, profile_path


def test_cli_packages_capture_and_plans_source_change(
    tmp_path, capture, monkeypatch, capsys
):
    repo, base, profile = setup_cli(tmp_path, capture)
    directory = tmp_path / "bundle"
    code, receipt = cli(
        monkeypatch,
        capsys,
        "pack",
        "--repo",
        repo,
        "--revision",
        base,
        "--profile",
        profile,
        "--query",
        tmp_path / "query.xml",
        "--roots",
        tmp_path / "roots.txt",
        "--native-bep",
        tmp_path / "native.bep.json",
        "--output",
        directory,
    )
    assert code == 0 and receipt["status"] == "packed"
    (repo / "lib/a.h").write_text("source change\n")
    git(repo, "commit", "--no-gpg-sign", "-qam", "source change")
    head = git(repo, "rev-parse", "HEAD")
    output = tmp_path / "plan.json"
    args = [
        "plan",
        "--repo",
        repo,
        "--base",
        base,
        f"--head={head}",
        "--profile",
        profile,
        "--bundle",
        directory,
        "--expected-digest",
        receipt["manifest_digest"],
        "--execution-mode",
        "selective",
        "--output",
        output,
    ]
    assert cli(monkeypatch, capsys, *args) == (
        0,
        {"status": "planned", "mode": "subset", "fallback": []},
    )
    first = output.read_bytes()
    assert json.loads(first)["selected"] == ["//lib:a_test"]
    assert cli(monkeypatch, capsys, *args)[0] == 0 and output.read_bytes() == first
    (repo / "ignored-untracked.h").write_text("unknown input")
    code, value = cli(monkeypatch, capsys, *args)
    assert code == 2 and value["code"] == "UNVERIFIED_NATIVE_CHECKOUT"
    assert output.read_bytes() == first


@pytest.mark.parametrize(
    "defect",
    [
        "missing_bundle",
        "digest",
        "profile",
        "dirty",
        "bad_commit",
        "anchor_tree",
        "missing_member",
    ],
)
def test_cli_invalid_evidence_fails_open_to_full_command(
    tmp_path, capture, monkeypatch, capsys, defect
):
    repo, base, profile_path = setup_cli(tmp_path, capture)
    _, _, profile, artifacts = capture
    directory = tmp_path / "bundle"
    packed = pack(directory, profile, base, artifacts)
    expected = packed.manifest_digest
    head = base
    if defect == "missing_bundle":
        directory = tmp_path / "absent"
    elif defect == "digest":
        expected = "c" * 64
    elif defect == "profile":
        profile_path.write_bytes(
            canonical(profile.model_dump() | {"repository": "other/project"})
        )
    elif defect == "dirty":
        (repo / "lib/a.h").write_text("dirty")
    elif defect == "bad_commit":
        head = "--dangerous-input"
    elif defect == "anchor_tree":
        alternate = artifacts["anchor.tree"].replace(b"100644", b"100755", 1)
        replacement = pack(
            tmp_path / "other", profile, base, artifacts | {"anchor.tree": alternate}
        )
        directory = tmp_path / "other"
        expected = replacement.manifest_digest
    elif defect == "missing_member":
        (directory / "query.xml").unlink()
    output = tmp_path / "plan.json"
    code, value = cli(
        monkeypatch,
        capsys,
        "plan",
        "--repo",
        repo,
        "--base",
        base,
        f"--head={head}",
        "--profile",
        profile_path,
        "--bundle",
        directory,
        "--expected-digest",
        expected,
        "--output",
        output,
    )
    if defect in {"dirty", "bad_commit"}:
        assert code == 2 and value["code"] == "UNVERIFIED_NATIVE_CHECKOUT"
        assert not output.exists()
        return
    assert code == 0 and value["mode"] == "full"
    report = json.loads(output.read_bytes())
    assert (
        report["patterns"] == ["..."]
        and report["production_omission_authorized"] is False
    )
    assert report["requires_independent_full_control"] is True
    assert "selected" not in report


def test_cli_refuses_report_over_capture(tmp_path, capture, monkeypatch, capsys):
    repo, base, profile = setup_cli(tmp_path, capture)
    before = profile.read_bytes()
    code, value = cli(
        monkeypatch,
        capsys,
        "plan",
        "--repo",
        repo,
        "--base",
        base,
        "--head",
        base,
        "--profile",
        profile,
        "--bundle",
        tmp_path / "absent",
        "--expected-digest",
        "a" * 64,
        "--output",
        profile,
    )
    assert code == 2 and value["code"] == "INVALID_OUTPUT"
    assert profile.read_bytes() == before
