"""Cached evidence must remain equivalent to fresh analysis or be discarded."""

import hashlib
import subprocess
from types import SimpleNamespace

import pytest

from smartci.contracts import Inventory
from smartci.contracts import TestUnit as Unit
from smartci.selection import Graph, digest
from smartci.typescript.collector import node_id
from smartci.typescript.collector import test_id as unit_id
from smartci.typescript.commands import planning
from smartci.typescript.models import TypeScriptConfig, TypeScriptSnapshot
from smartci.typescript.precomputed import load_base_map


def commit(root):
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def save(snapshot, path):
    snapshot.digest = digest(snapshot.model_dump(exclude={"digest"}))
    payload = snapshot.model_dump_json().encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    (tmp_path / "out").mkdir()
    root = tmp_path / "app"
    root.mkdir()
    for p in [
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "code.ts",
        "test.ts",
    ]:
        (root / p).write_text("{}")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    base = commit(root)
    config = TypeScriptConfig(
        schema_version="1", repository="fixture", projects=["tsconfig.json"]
    )
    files = sorted(p.name for p in root.iterdir() if p.is_file())
    nodes = {p: node_id(p) for p in files}
    provenance = {
        "configuration": digest(config.model_dump()),
        "implementation": "current",
    }
    inventory = Inventory(
        schema_version="1",
        repository="fixture",
        complete=True,
        environment=digest(provenance),
        tests=[
            Unit(
                id=unit_id("test.ts"),
                path="test.ts",
                runner="vitest",
                granularity="file",
            )
        ],
    )
    graph = Graph(
        schema_version="1",
        repository="fixture",
        commit=base,
        complete=True,
        owners=nodes,
        dependencies={
            n: ([node_id("code.ts")] if p == "test.ts" else [])
            for p, n in nodes.items()
        },
        tests={unit_id("test.ts"): node_id("test.ts")},
    )
    snapshot = TypeScriptSnapshot(
        schema_version="1",
        repository="fixture",
        graph=graph,
        inventory=inventory,
        files=["test.ts"],
        widened=[],
        gaps=[],
        analyzed=["code.ts", "test.ts"],
        provenance=provenance,
    )
    path = tmp_path / "base-map.json"
    sha = save(snapshot, path)
    (root / "code.ts").write_text("changed")
    head = commit(root)
    return root, base, head, config, snapshot, path, sha


def test_exact_verified_map_loads(evidence):
    root, base, head, config, snapshot, path, sha = evidence
    assert load_base_map(root, base, head, config, path, sha) == snapshot


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "digest",
        "commit",
        "repository",
        "configuration",
        "tree",
        "inventory",
        "incomplete",
        "gap",
        "environment",
        "internal_digest",
        "untrusted_path",
        "symlink",
        "dependency",
    ],
)
def test_invalid_maps_rejected(evidence, mutation):
    root, base, head, config, snapshot, path, sha = evidence
    if mutation == "bytes":
        path.write_text("{}")
    elif mutation == "digest":
        sha = "0" * 64
    elif mutation == "internal_digest":
        snapshot.digest = "0" * 64
        path.write_text(snapshot.model_dump_json())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == "untrusted_path":
        path = root / "map.json"
        sha = save(snapshot, path)
    elif mutation == "symlink":
        link = path.with_name("link.json")
        link.symlink_to(path)
        path = link
    elif mutation == "dependency":
        (root / "package.json").write_text('{"changed":true}')
    else:
        if mutation == "commit":
            snapshot.graph.commit = head
        elif mutation == "repository":
            snapshot.repository = "other"
        elif mutation == "configuration":
            snapshot.provenance["configuration"] = "wrong"
        elif mutation == "tree":
            del snapshot.graph.owners["code.ts"]
        elif mutation == "inventory":
            snapshot.inventory.tests = []
        elif mutation == "incomplete":
            snapshot.graph.complete = False
        elif mutation == "gap":
            snapshot.gaps = ["unknown"]
        elif mutation == "environment":
            snapshot.inventory.environment = "other"
        sha = save(snapshot, path)
    with pytest.raises(ValueError):
        load_base_map(root, base, head, config, path, sha)


@pytest.mark.parametrize(
    "cache_mode", ["hit", "missing", "tampered", "stale_tool", "runtime"]
)
def test_planning_validates_or_reconstructs_without_changing_selection(
    evidence, tmp_path, monkeypatch, cache_mode
):
    root, base, revision, config, saved, path, sha = evidence
    head = saved.model_copy(deep=True)
    head.graph.commit = revision
    head.digest = digest(head.model_dump(exclude={"digest"}))
    rebuilt = []

    def rebuild(*args):
        rebuilt.append(True)
        return saved

    monkeypatch.setattr("smartci.typescript.commands.collect", lambda *args: head)
    monkeypatch.setattr("smartci.typescript.commands.rebuild_base", rebuild)
    if cache_mode == "missing":
        path.unlink()
    elif cache_mode == "tampered":
        path.write_text("{}")
    elif cache_mode in ("stale_tool", "runtime"):
        cached = saved.model_copy(deep=True)
        cached.provenance[
            "implementation" if cache_mode == "stale_tool" else "node"
        ] = "stale"
        cached.inventory.environment = digest(cached.provenance)
        sha = save(cached, path)
    info = {}
    report, _ = planning(
        SimpleNamespace(root=root),
        config,
        base,
        False,
        tmp_path / "out",
        path,
        sha,
        info,
    )
    assert report.execution == "subset" and report.fallback == []
    assert report.selected == [unit_id("test.ts")]
    assert info["status"] == ("hit" if cache_mode == "hit" else "miss")
    assert bool(rebuilt) == (cache_mode != "hit")


def test_invalid_map_and_failed_rebuild_require_full_suite(
    evidence, tmp_path, monkeypatch
):
    root, base, revision, config, saved, path, sha = evidence
    head = saved.model_copy(deep=True)
    head.graph.commit = revision
    monkeypatch.setattr("smartci.typescript.commands.collect", lambda *args: head)

    def unavailable(*args):
        raise ValueError("no dependency environment")

    monkeypatch.setattr("smartci.typescript.commands.rebuild_base", unavailable)
    path.unlink()
    report, _ = planning(
        SimpleNamespace(root=root), config, base, False, tmp_path / "out", path, sha, {}
    )
    assert report.execution == "full" and report.fallback == [
        "MAP_REBUILD_OR_DISCOVERY_FAILED"
    ]
