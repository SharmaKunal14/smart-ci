"""Deterministic candidate planning for a reviewed native C++ build profile.

Reuse assumes the reviewed build profile derives its graph from build definitions
and paths, not C++ file contents. Paired evaluation is the default. Single-job
selection requires explicit policy from the trusted CI entry point; agents and
repository evidence cannot enable it.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Literal

from smartci.contracts import TestUnit

from .audit import NativeInventory, reconcile_graph
from .graph import MAX_NODES, QueryError, QueryGraph

MAX_TREE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    oid: str


def parse_tree(raw: bytes) -> dict[str, TreeEntry]:
    """Parse bounded `git ls-tree -rz --full-tree` output, including mode changes."""
    if not raw or len(raw) > MAX_TREE_BYTES or not raw.endswith(b"\0"):
        raise QueryError("invalid or excessive Git tree")
    result: dict[str, TreeEntry] = {}
    for row in raw[:-1].split(b"\0"):
        try:
            metadata, path = row.decode("utf-8").split("\t", 1)
            mode, kind, oid = metadata.split(" ")
            if len(path) > 1024:
                raise ValueError("path exceeds bound")
            TestUnit.relative_path(path)
        except ValueError as exc:
            raise QueryError("invalid Git tree entry") from exc
        if (
            mode not in {"100644", "100755", "120000", "160000"}
            or kind != ("commit" if mode == "160000" else "blob")
            or not re.fullmatch(r"[0-9a-f]{40}", oid)
            or path in result
            or len(result) >= MAX_NODES
        ):
            raise QueryError("unsupported or duplicate Git tree entry")
        result[path] = TreeEntry(mode, oid)
    return dict(sorted(result.items()))


def changed_paths(
    before: dict[str, TreeEntry], after: dict[str, TreeEntry]
) -> list[str]:
    return sorted(
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    )


def tree_digest(tree: dict[str, TreeEntry]) -> str:
    return hashlib.sha256(
        json.dumps(
            {path: asdict(entry) for path, entry in sorted(tree.items())},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def control_path(path: str) -> bool:
    # Only the reviewed pilot's setup files may differ from the map anchor.
    # Changes to these files *within the PR* still require full fallback.
    return path.startswith((".github/workflows/", ".smartci/"))


def reusable_change(
    path: str,
    before: dict[str, TreeEntry],
    after: dict[str, TreeEntry],
    graph: QueryGraph,
) -> bool:
    return (
        path in before
        and path in after
        and before[path].mode == after[path].mode == "100644"
        and PurePosixPath(path).suffix in {".cc", ".h"}
        and path in graph.source_owners
    )


def candidate_plan(
    anchor: dict[str, TreeEntry],
    base: dict[str, TreeEntry],
    head: dict[str, TreeEntry],
    graph: QueryGraph,
    roots: list[str],
    native: NativeInventory,
    *,
    must_run: tuple[str, ...] = (),
    execution_mode: Literal["paired", "selective"] = "paired",
) -> dict[str, object]:
    """Reuse an authenticated map only while both revisions preserve its inputs.

    Added/deleted/renamed sources, modes, definitions, dependencies, resources,
    configuration, unknown paths and empty impact all retain native full scope.
    Removing a C++ include cannot remove a BUILD edge from this cached graph.
    """
    if execution_mode not in {"paired", "selective"}:
        raise QueryError("unsupported native execution policy")
    reconcile_graph(graph, roots, native)
    changes = changed_paths(base, head)
    fallback = []
    if not set(must_run) <= set(native.tests):
        fallback.append("INVALID_MUST_RUN")
    for revision in (base, head):
        if any(
            not control_path(path)
            and not reusable_change(path, anchor, revision, graph)
            for path in changed_paths(anchor, revision)
        ):
            fallback.append("MAP_INPUTS_CHANGED")
    if not changes:
        fallback.append("NO_CODE_CHANGE")
    elif any(not reusable_change(path, base, head, graph) for path in changes):
        fallback.append("UNSUPPORTED_OR_RISK_CHANGE")
    witnesses: dict[str, list[str]] = {}
    selected = set(native.tests)
    if not fallback:
        witnesses = graph.affected(changes)
        selected = (set(witnesses) & set(native.tests)) | set(must_run)
        if not selected:
            fallback.append("NO_IMPACT_EVIDENCE")
            selected = set(native.tests)
    omitted = sorted(set(native.tests) - selected)
    # Retain the original wildcard and subtract only eligible native tests.
    # Replacing it with selected test labels would silently lose build checks.
    patterns = ["...", *("-" + name for name in omitted)]
    # Leave headroom below the native evidence reader's 64 KiB/2048-pattern
    # bound. Large selections must fall back before executing an unauditable job.
    if (
        len(patterns) > 1000
        or len(json.dumps({"pattern": {"pattern": patterns}})) > 60_000
    ):
        fallback.append("TARGET_PATTERN_EVIDENCE_LIMIT")
        selected = set(native.tests)
        omitted, patterns = [], ["..."]
    report: dict[str, object] = {
        "schema_version": "smartci.bazel-candidate.v1",
        "mode": "subset" if omitted else "full",
        "fallback": sorted(set(fallback)),
        "changed_paths": changes,
        "selected": sorted(selected),
        "omitted": omitted,
        "build_only": list(native.build_only),
        "build_configurations": {
            name: list(native.build_configurations[name])
            for name in sorted(set(native.build_only) | selected)
        },
        "patterns": patterns,
        "witnesses": {
            name: witnesses[name] for name in sorted(selected) if name in witnesses
        },
        "must_run": sorted(set(must_run)),
        "trees": {
            "anchor": tree_digest(anchor),
            "base": tree_digest(base),
            "head": tree_digest(head),
        },
        "production_omission_authorized": execution_mode == "selective"
        and bool(omitted),
        "requires_independent_full_control": execution_mode == "paired",
    }
    report["digest"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report
