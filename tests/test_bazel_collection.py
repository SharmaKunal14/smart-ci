import json
import sys

import pytest
from test_bazel_bundle import (
    capture,  # noqa: F401 -- shared pytest fixture
    git,
)

from smartci.bazel.bundle import load
from smartci.bazel.collection import CaptureCommand, CaptureConfig, collect, run_command
from smartci.bazel.graph import QueryError
from smartci.cli import main


@pytest.fixture
def collector(tmp_path, request):
    repo, revision, profile, artifacts = request.getfixturevalue("capture")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name, value in artifacts.items():
        (inputs / name).write_bytes(value)
    driver = tmp_path / "driver.py"
    driver.write_text(
        """import os,sys,time
from pathlib import Path
stage,source,destination,defect=sys.argv[1:]
assert 'OPENAI_API_KEY' not in os.environ and 'GH_TOKEN' not in os.environ
source,destination=Path(source),Path(destination)
(source/(stage+'.called')).write_text('called')
if defect == stage+'-fail': raise SystemExit(3)
if defect == stage+'-timeout': time.sleep(30)
if stage == 'native':
    (destination/'native.bep.json').write_bytes((source/'native.bep.json').read_bytes())
    if defect == 'dirty': Path('lib/a.h').write_text('changed during execution')
else:
    for name in ('query.xml','roots.txt'):
        (destination/name).write_bytes((source/name).read_bytes())
    (destination/'bazel-version.txt').write_text('bazel 9.1.0\\n')
    if defect == 'version': (destination/'bazel-version.txt').write_text('bazel 9.2.0')
    if defect == 'tamper': (destination/'native.bep.json').write_text('{}')
    if defect == 'missing': (destination/'query.xml').unlink()
"""
    )

    def config(defect="none"):
        return CaptureConfig(
            schema_version="1",
            profile=profile,
            **{
                stage: CaptureCommand(
                    argv=[
                        sys.executable,
                        str(driver),
                        stage,
                        str(inputs),
                        "{capture}",
                        defect,
                    ],
                    timeout_seconds=1 if defect.endswith("timeout") else 10,
                )
                for stage in ("native", "query")
            },
        )

    return repo, revision, config, inputs


def test_fresh_capture_runs_native_and_query_and_publishes_valid_bundle(
    tmp_path, collector, monkeypatch
):
    repo, revision, config, inputs = collector
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-native-code")
    monkeypatch.setenv("GH_TOKEN", "must-not-reach-native-code")
    output = tmp_path / "out"
    report = collect(repo, revision, config(), output)
    assert report["status"] == "ready" and report["cache"] == "not_supplied"
    assert report["native_exit"] == report["query_exit"] == 0
    assert (inputs / "native.called").exists() and (inputs / "query.called").exists()
    bundle = load(output / "bundle", report["manifest_digest"], config().profile)
    assert bundle.native.tests == ("//lib:a_test", "//lib:b_test")
    assert bundle.native.build_only == ("//lib:binary",)
    assert json.loads((output / "collection.json").read_bytes()) == report


@pytest.mark.parametrize(
    "defect,error",
    [
        ("native-fail", "NATIVE_EXECUTION_FAILED"),
        ("native-timeout", "NATIVE_EXECUTION_FAILED"),
        ("query-fail", "QUERY_EXECUTION_FAILED"),
        ("query-timeout", "QUERY_EXECUTION_FAILED"),
        ("dirty", "NATIVE_VALIDATION_FAILED"),
        ("version", "QUERY_VALIDATION_FAILED"),
        ("tamper", "QUERY_VALIDATION_FAILED"),
        ("missing", "QUERY_VALIDATION_FAILED"),
    ],
)
def test_failed_or_unverifiable_capture_never_publishes_a_map(
    tmp_path, collector, defect, error
):
    repo, revision, config, _ = collector
    output = tmp_path / "out"
    report = collect(repo, revision, config(defect), output)
    assert report["status"] == "failed" and report["error"] == error
    assert report["manifest_digest"] is None
    assert not (output / "bundle/manifest.json").exists()


def test_native_zero_exit_with_incomplete_evidence_does_not_run_query(
    tmp_path, collector
):
    repo, revision, config, inputs = collector
    (inputs / "native.bep.json").write_text("{}\n")
    report = collect(repo, revision, config(), tmp_path / "out")
    assert report["error"] == "NATIVE_VALIDATION_FAILED"
    assert not (inputs / "query.called").exists()


@pytest.mark.parametrize("source_change", [False, True])
def test_compatible_map_reuse_runs_no_native_or_query_command(
    tmp_path, collector, source_change, monkeypatch
):
    repo, revision, config, inputs = collector
    first = collect(repo, revision, config(), tmp_path / "first")
    for stage in ("native", "query"):
        (inputs / (stage + ".called")).unlink()
    if source_change:
        (repo / "lib/a.h").write_text("different source")
        git(repo, "commit", "--no-gpg-sign", "-qam", "source")
        revision = git(repo, "rev-parse", "HEAD")

    def unexpected_command(*args):
        raise AssertionError("cache hit must execute no native command")

    monkeypatch.setattr("smartci.bazel.collection.run_command", unexpected_command)
    second = collect(
        repo,
        revision,
        config(),
        tmp_path / "second",
        reuse=tmp_path / "first/bundle",
        expected_digest=first["manifest_digest"],
    )
    assert second["status"] == "ready" and second["cache"] == "reused"
    assert second["manifest_digest"] == first["manifest_digest"]
    assert second["native_exit"] is None and second["query_exit"] is None
    assert (
        not (inputs / "native.called").exists()
        and not (inputs / "query.called").exists()
    )


@pytest.mark.parametrize(
    "defect",
    ["missing", "tampered", "digest", "build-change", "added-source", "commands"],
)
def test_unusable_maps_automatically_rebuild(tmp_path, collector, defect):
    repo, revision, config, inputs = collector
    first = collect(repo, revision, config(), tmp_path / "first")
    directory = tmp_path / "first/bundle"
    digest = first["manifest_digest"]
    updated_config = config()
    for stage in ("native", "query"):
        (inputs / (stage + ".called")).unlink()
    if defect == "missing":
        directory = tmp_path / "absent"
    elif defect == "tampered":
        (directory / "query.xml").write_text("{}")
    elif defect == "digest":
        digest = "a" * 64
    elif defect == "commands":
        values = updated_config.model_dump()
        values["native"]["timeout_seconds"] += 1
        updated_config = CaptureConfig.model_validate(values)
    else:
        path = "lib/BUILD.bazel" if defect == "build-change" else "lib/added.h"
        (repo / path).write_text("changed")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-qm", "change graph inputs")
        revision = git(repo, "rev-parse", "HEAD")
    second = collect(
        repo,
        revision,
        updated_config,
        tmp_path / "second",
        reuse=directory,
        expected_digest=digest,
    )
    assert second["status"] == "ready" and second["cache"] == "rejected"
    assert second["native_exit"] == second["query_exit"] == 0
    assert second["map_revision"] == revision
    assert (inputs / "native.called").exists() and (inputs / "query.called").exists()


def test_invalid_checkout_does_not_start_capture(tmp_path, collector):
    repo, revision, config, inputs = collector
    (repo / "lib/a.h").write_text("dirty")
    with pytest.raises(ValueError):
        collect(repo, revision, config(), tmp_path / "out")
    assert not (inputs / "native.called").exists()
    assert not (tmp_path / "out").exists()


def test_collection_cannot_overwrite_inputs_or_previous_capture(tmp_path, collector):
    repo, revision, config, _ = collector
    with pytest.raises(QueryError, match="overlaps"):
        collect(repo, revision, config(), repo / "output")
    collect(repo, revision, config(), tmp_path / "first")
    with pytest.raises(FileExistsError):
        collect(repo, revision, config(), tmp_path / "first")


def test_arguments_are_literal_without_shell_expansion(tmp_path, collector):
    repo, _, _, _ = collector
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    argument = "$(touch must-not-exist);literal"
    command = CaptureCommand(
        argv=[
            sys.executable,
            "-c",
            "import sys;from pathlib import Path;Path(sys.argv[1]).write_text(sys.argv[2])",
            "{capture}/argv",
            argument,
        ],
        timeout_seconds=5,
    )
    assert run_command(command, repo, capture_dir) == 0
    assert (capture_dir / "argv").read_text() == argument
    assert not (repo / "must-not-exist").exists()


@pytest.mark.parametrize(
    "argv", [["relative"], ["/bin/echo", "bad\narg"], ["/{repo}/untrusted"]]
)
def test_unbounded_or_ambiguous_command_config_is_rejected(argv):
    with pytest.raises(ValueError):
        CaptureCommand(argv=argv, timeout_seconds=5)


def test_collection_cli_requires_complete_reuse_identity(
    tmp_path, collector, monkeypatch
):
    repo, revision, config, inputs = collector
    policy = tmp_path / "config.json"
    policy.write_text(config().model_dump_json())
    output = tmp_path / "out"
    arguments = [
        "smartci",
        "bazel",
        "collect",
        "--repo",
        str(repo),
        "--revision",
        revision,
        "--config",
        str(policy),
        "--output",
        str(output),
    ]
    monkeypatch.setattr(
        sys, "argv", arguments + ["--reuse-bundle", str(tmp_path / "missing")]
    )
    assert main() == 2
    assert not (inputs / "native.called").exists()
    monkeypatch.setattr(sys, "argv", arguments)
    assert main() == 0
    assert json.loads((output / "collection.json").read_bytes())["status"] == "ready"
