"""Replayable local plans from compatible collector snapshots; no execution."""

from collections import deque
from pathlib import Path

from smartci.adapters.suite import current_clean_head
from smartci.git_changes import changes_from_git
from smartci.selection import (
    Changes,
    Report,
    SelectionPolicy,
    digest,
    fallback,
    finish,
    select,
)

from .collector import implementation_digest
from .models import Snapshot


def required_full_from_head(
    root: Path, base_commit: str, head: Snapshot, policy: SelectionPolicy
) -> Report | None:
    """Avoid base discovery only when validated head evidence requires full tests.

    None means both revision maps are still required. This path never authorizes
    a subset and never fabricates a base snapshot or claims base completeness.
    """
    if current_clean_head(root) != head.graph.commit:
        raise ValueError("stale or dirty head snapshot")
    if head.repository != policy.repository:
        raise ValueError("repository mismatch")
    if head.provenance.implementation_digest != implementation_digest():
        raise ValueError("collector version mismatch")
    changes = changes_from_git(root, base_commit, head.graph.commit, head.repository)
    if changes.base != base_commit:
        raise ValueError("exact merge base required")
    if head.graph.complete and head.inventory.complete:
        return None
    result = fallback("INCOMPLETE_EVIDENCE", head.inventory)
    result.comparison = {"base": base_commit, "head": head.graph.commit}
    result.evidence = {
        "changes": digest(changes.model_dump()),
        "inventory": digest(head.inventory.model_dump()),
        "head_graph": digest(head.graph.model_dump()),
        "head_snapshot": head.digest,
        "policy": digest(policy.model_dump()),
    }
    result.warnings = [
        "BASE_DISCOVERY_SKIPPED:HEAD_REQUIRES_FULL",
        *sorted(
            f"COLLECTION_GAP:{g.code}:{g.path or 'environment'}:{g.line}"
            for g in head.provenance.gaps
        ),
    ]
    for test in head.inventory.tests:
        result.reasons[test.id].append(f"TEST_FILE:{test.path}")
    return finish(result)


def dependency_paths(
    report: Report, changes: Changes, base: Snapshot, head: Snapshot
) -> None:
    reverse: dict[str, set[str]] = {}
    labels = {}
    seeds: set[str] = set()
    for snapshot in (base, head):
        graph = snapshot.graph
        labels.update({node: path for path, node in graph.owners.items()})
        seeds.update(graph.owners[p] for p in changes.paths if p in graph.owners)
        for node, dependencies in graph.dependencies.items():
            for dependency in dependencies:
                reverse.setdefault(dependency, set()).add(node)
    previous: dict[str, str | None] = {node: None for node in sorted(seeds)}
    pending = deque(sorted(seeds))
    while pending:
        node = pending.popleft()
        for dependent in sorted(reverse.get(node, set())):
            if dependent not in previous:
                previous[dependent] = node
                pending.append(dependent)
    for test in report.selected:
        node = head.graph.tests[test]
        if node not in previous:
            continue
        path: list[str] = []
        cursor: str | None = node
        while cursor is not None and len(path) < 64:
            path.append(labels.get(cursor, cursor))
            cursor = previous[cursor]
        if cursor is not None:
            report.reasons[test].append("DEPENDENCY_PATH_EXCEEDS_DISPLAY_LIMIT")
        else:
            report.reasons[test].append(
                "DEPENDENCY_PATH:" + " -> ".join(reversed(path))
            )


def plan(root: Path, base: Snapshot, head: Snapshot, policy: SelectionPolicy) -> Report:
    result: Report
    changes = None
    if current_clean_head(root) != head.graph.commit:
        result = fallback("STALE_OR_DIRTY_WORKSPACE", head.inventory)
    elif base.provenance.config != head.provenance.config:
        result = fallback("COLLECTOR_CONFIGURATION_MISMATCH", head.inventory)
    elif base.inventory.environment != head.inventory.environment:
        result = fallback("ENVIRONMENT_MISMATCH", head.inventory)
    elif any(
        s.provenance.implementation_digest != implementation_digest()
        for s in (base, head)
    ):
        result = fallback("COLLECTOR_VERSION_MISMATCH", head.inventory)
    else:
        try:
            changes = changes_from_git(
                root, base.graph.commit, head.graph.commit, head.repository
            )
            result = select(changes, head.inventory, base.graph, head.graph, policy)
        except (OSError, ValueError):
            result = fallback("INVALID_GIT_COMPARISON", head.inventory)
    result.comparison = {"base": base.graph.commit, "head": head.graph.commit}
    result.evidence.update({"base_snapshot": base.digest, "head_snapshot": head.digest})
    result.warnings.extend(
        sorted(
            {
                f"COLLECTION_GAP:{g.code}:{g.path or 'environment'}:{g.line}"
                for s in (base, head)
                for g in s.provenance.gaps
            }
        )
    )
    if result.mode == "subset" and changes is not None:
        dependency_paths(result, changes, base, head)
    paths = {test.id: test.path for test in head.inventory.tests}
    for test in result.selected:
        result.reasons[test] = sorted(
            {*result.reasons[test], f"TEST_FILE:{paths[test]}"}
        )
    return finish(result)
