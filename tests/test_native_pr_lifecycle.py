import json

import pytest
from test_bazel_bundle import capture  # noqa: F401
from test_bazel_execution import execution_case  # noqa: F401

from smartci.bazel import lifecycle as module
from smartci.bazel.bundle import canonical
from smartci.bazel.collection import CaptureConfig


@pytest.mark.parametrize("cache", ["hit", "missing", "incompatible", "failed-rebuild"])
@pytest.mark.parametrize("custom_publisher", [False, True])
def test_native_pr_uses_validated_map_or_rebuilds_base_then_restores_head(
    tmp_path, request, monkeypatch, cache, custom_publisher
):
    repo, base, head, config, _, _, _ = request.getfixturevalue("execution_case")
    execution = config()
    capture_config = CaptureConfig(
        schema_version="1",
        profile=execution.profile,
        native=execution.full,
        query=execution.full,
    )
    config_reads = []

    def read_config(path):
        config_reads.append(path)
        return capture_config

    monkeypatch.setattr(module, "read_config", read_config)
    monkeypatch.setattr(module, "read_execution_config", lambda _: execution)
    fetched = tmp_path / "fetched"
    fetched.mkdir()
    if cache != "missing":
        (fetched / "fetch.json").write_bytes(
            canonical({"status": "ready", "manifest_digest": "a" * 64})
        )

    def reuse(*args):
        if cache != "hit":
            raise ValueError("incompatible map")

    monkeypatch.setattr(module, "reusable_bundle", reuse)
    collected = []

    def collect(root, revision, config, output):
        module.verify_checkout(root, base)
        collected.append(revision)
        return {
            "status": "failed" if cache == "failed-rebuild" else "ready",
            "manifest_digest": "b" * 64,
        }

    monkeypatch.setattr(module, "collect", collect)
    executions = []

    def execute(root, actual_base, actual_head, *args, **kwargs):
        module.verify_checkout(root, head)
        assert actual_base == base and actual_head == head
        executions.append(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(module, "execute", execute)
    report = module.run(
        repo,
        base,
        head,
        fetched,
        tmp_path / "capture.json",
        tmp_path / "execution.json",
        tmp_path / "out",
        tmp_path / "publisher.json" if custom_publisher else None,
    )
    assert report["status"] == "passed" and len(executions) == 1
    if custom_publisher and cache != "missing":
        assert tmp_path / "publisher.json" in config_reads
    assert collected == ([] if cache == "hit" else [base])
    if cache == "failed-rebuild":
        assert executions[0]["bundle_path"] is None
    elif cache == "hit":
        assert executions[0]["bundle_path"] == fetched / "bundle"
    else:
        assert executions[0]["bundle_path"] == tmp_path / "out/rebuild/bundle"
    lifecycle = json.loads((tmp_path / "out/lifecycle.json").read_bytes())
    assert lifecycle["map"] == (
        "retrieved"
        if cache == "hit"
        else "unavailable"
        if cache == "failed-rebuild"
        else "rebuilt"
    )


def test_failed_checkout_restore_never_executes_wrong_revision(
    tmp_path, request, monkeypatch
):
    repo, base, head, config, _, _, _ = request.getfixturevalue("execution_case")
    execution = config()
    capture_config = CaptureConfig(
        schema_version="1",
        profile=execution.profile,
        native=execution.full,
        query=execution.full,
    )
    monkeypatch.setattr(module, "read_config", lambda _: capture_config)
    monkeypatch.setattr(module, "read_execution_config", lambda _: execution)

    def checkout(root, revision):
        if revision == head:
            raise ValueError("cannot restore head")

    monkeypatch.setattr(module, "checkout", checkout)
    monkeypatch.setattr(module, "collect", lambda *args: {"status": "failed"})
    monkeypatch.setattr(
        module,
        "execute",
        lambda *args, **kwargs: pytest.fail("wrong revision must not execute"),
    )
    with pytest.raises(ValueError, match="cannot restore head"):
        module.run(
            repo,
            base,
            head,
            tmp_path / "missing",
            tmp_path / "c",
            tmp_path / "e",
            tmp_path / "out",
        )
