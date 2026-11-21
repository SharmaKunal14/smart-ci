"""Concurrent discovery must join both workers and reject partial or stale maps."""

from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from smartci.selection import Changes
from smartci.typescript.commands import planning
from smartci.typescript.models import TypeScriptConfig


@pytest.mark.parametrize("failed_worker", ["head", "base"])
def test_discovery_failure_waits_for_both_workers_and_falls_back(
    tmp_path, monkeypatch, failed_worker
):
    barrier, finished = Barrier(2, timeout=5), Event()
    monkeypatch.setattr(
        "smartci.typescript.commands.current_clean_head", lambda root: "b" * 40
    )
    monkeypatch.setattr(
        "smartci.typescript.commands.changes_from_git",
        lambda *args: Changes(
            schema_version="1",
            repository="fixture",
            base="a" * 40,
            head="b" * 40,
            paths=["code.ts"],
        ),
    )
    snapshot = SimpleNamespace(graph=SimpleNamespace(commit="b" * 40), inventory=None)

    def worker(name):
        barrier.wait()
        if name == failed_worker:
            raise ValueError("discovery unavailable")
        finished.set()
        return snapshot

    monkeypatch.setattr(
        "smartci.typescript.commands.collect", lambda *args: worker("head")
    )
    monkeypatch.setattr(
        "smartci.typescript.commands.rebuild_base", lambda *args: worker("base")
    )
    report, _ = planning(
        SimpleNamespace(root=tmp_path),
        TypeScriptConfig(
            schema_version="1", repository="fixture", projects=["tsconfig.json"]
        ),
        "a" * 40,
        False,
        tmp_path,
    )
    assert finished.is_set()
    assert report.execution == "full"
    assert report.fallback == ["MAP_REBUILD_OR_DISCOVERY_FAILED"]


@pytest.mark.parametrize("changed", ["head_map", "base_map", "working_tree"])
def test_changed_revision_during_parallel_analysis_cannot_select(
    tmp_path, monkeypatch, changed
):
    calls = iter(["b" * 40, "c" * 40 if changed == "working_tree" else "b" * 40])
    monkeypatch.setattr(
        "smartci.typescript.commands.current_clean_head", lambda root: next(calls)
    )
    monkeypatch.setattr(
        "smartci.typescript.commands.changes_from_git",
        lambda *args: Changes(
            schema_version="1",
            repository="fixture",
            base="a" * 40,
            head="b" * 40,
            paths=["code.ts"],
        ),
    )

    def snapshot(commit):
        return SimpleNamespace(graph=SimpleNamespace(commit=commit), inventory=None)

    monkeypatch.setattr(
        "smartci.typescript.commands.collect",
        lambda *args: snapshot("c" * 40 if changed == "head_map" else "b" * 40),
    )
    monkeypatch.setattr(
        "smartci.typescript.commands.rebuild_base",
        lambda *args: snapshot("c" * 40 if changed == "base_map" else "a" * 40),
    )
    report, _ = planning(
        SimpleNamespace(root=tmp_path),
        TypeScriptConfig(
            schema_version="1", repository="fixture", projects=["tsconfig.json"]
        ),
        "a" * 40,
        False,
        tmp_path,
    )
    assert report.execution == "full"
    assert report.fallback == ["MAP_REBUILD_OR_DISCOVERY_FAILED"]
