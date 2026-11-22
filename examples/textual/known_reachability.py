"""Inspect recorded graph breadth; never turn missing edges into omission authority."""

from smartci.discovery.models import Snapshot
from smartci.discovery.planning import dependency_paths
from smartci.selection import Changes, digest, fallback

MAX_INDIVIDUAL_PATHS = 16
MAX_WITNESSES = 20


def reached(changes: Changes, base: Snapshot, head: Snapshot) -> dict[str, object]:
    # Reuse production traversal, including removed edges and bounded explanations.
    # This temporary full report is not published or passed to a runner.
    report = fallback("DIAGNOSTIC_ONLY", head.inventory)
    dependency_paths(report, changes, base, head)
    paths = {unit.id: unit.path for unit in head.inventory.tests}
    explanations = {
        test: sorted(
            reason
            for reason in reasons
            if reason.startswith("DEPENDENCY_PATH:")
            or reason == "DEPENDENCY_PATH_EXCEEDS_DISPLAY_LIMIT"
        )
        for test, reasons in report.reasons.items()
    }
    impacted = sorted(
        (test for test, reasons in explanations.items() if reasons),
        key=lambda test: (paths[test], test),
    )
    all_files = {unit.path for unit in head.inventory.tests}
    reached_files = sorted({paths[test] for test in impacted})
    witnesses = [
        {"test_id": test, "test_file": paths[test], "reasons": explanations[test]}
        for test in impacted[:MAX_WITNESSES]
    ]
    return {
        "changed_paths": sorted(set(changes.paths)),
        "test_units_reached": len(impacted),
        "test_files_reached": len(reached_files),
        "test_files_total": len(all_files),
        "test_files_not_reached": len(all_files) - len(reached_files),
        "reached_test_files": reached_files,
        "witnesses": witnesses,
        "witnesses_truncated": len(impacted) > len(witnesses),
    }


def summarize(changes: Changes, base: Snapshot, head: Snapshot) -> dict[str, object]:
    if (
        changes.repository != base.repository
        or changes.repository != head.repository
        or changes.base != base.graph.commit
        or changes.head != head.graph.commit
    ):
        raise ValueError("reachability comparison does not match snapshots")
    mapped = sorted(
        set(changes.paths) & (base.graph.owners.keys() | head.graph.owners.keys())
    )
    individual = [
        reached(changes.model_copy(update={"paths": [path]}), base, head)
        for path in mapped[:MAX_INDIVIDUAL_PATHS]
    ]
    report = {
        "schema": "smartci.known-reachability.v1",
        "repository": changes.repository,
        "comparison": {"base": changes.base, "head": changes.head},
        "snapshots": {"base": base.digest, "head": head.digest},
        "omission_authorized": False,
        "test_execution_performed": False,
        "ci_savings_demonstrated": False,
        "execution_required": "full",
        "unmapped_changed_paths": sorted(set(changes.paths) - set(mapped)),
        "aggregate": reached(changes, base, head),
        "per_mapped_changed_path": individual,
        "individual_paths_truncated": len(mapped) > len(individual),
        "limits": [
            "Reachability is through recorded base/head edges, not verified runtime necessity.",
            "Unreached tests are not proven irrelevant; unknown behavior still requires full execution.",
            "A count of test files does not establish elapsed-time or resource savings.",
        ],
    }
    return report | {"digest": digest(report)}
