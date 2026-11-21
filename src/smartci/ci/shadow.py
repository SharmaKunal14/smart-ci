"""Pure comparison and local preparation. Full native execution is a separate CI step."""

from pathlib import Path

from smartci.adapters.runners import PyReport
from smartci.adapters.suite import current_clean_head
from smartci.discovery.models import Snapshot
from smartci.selection import Report, digest

from .models import Baseline, Comparison, ComparisonStatus, Context, ShadowPolicy


def compare(
    context: Context,
    snapshot: Snapshot,
    decision: Report,
    native: PyReport,
    native_exit: int,
    policy: ShadowPolicy,
    root: Path,
) -> Comparison:
    ids = set(native.collected)
    expected_ids = snapshot.provenance.native_cases_digest
    known: list[str] = []
    unexpected: list[str] = []
    for case, outcome in sorted(native.results.items()):
        if outcome != "skipped":
            continue
        path = case.split("::")[0]
        reviewed = any(
            rule.case == case
            and rule.platform == snapshot.provenance.environment.platform
            and rule.reason == native.skip_reasons.get(case)
            and rule.source_digest == snapshot.provenance.sources.get(path)
            for rule in policy.expected_skips
        )
        (known if reviewed else unexpected).append(case)
    failed = sorted(
        case for case, outcome in native.results.items() if outcome == "failed"
    )
    selected_paths = {
        t.path for t in snapshot.inventory.tests if t.id in decision.selected
    }
    missed = (
        sorted({case.split("::")[0] for case in failed} - selected_paths)
        if decision.mode == "subset"
        else []
    )
    complete = (
        context.repository == snapshot.repository
        and context.tested == snapshot.graph.commit == current_clean_head(root)
        and digest(decision.model_dump(exclude={"digest"})) == decision.digest
        and decision.execution == "full"
        and decision.comparison == {"base": context.base, "head": context.tested}
        and set(decision.selected).isdisjoint(decision.omitted)
        and set(decision.selected) | set(decision.omitted)
        == {t.id for t in snapshot.inventory.tests}
        and decision.evidence.get("head_snapshot") == snapshot.digest
        and len(ids) == len(native.collected) == snapshot.provenance.native_case_count
        and digest(sorted(native.collected)) == expected_ids
        and ids == set(native.results)
        and sorted(native.plugins) == snapshot.provenance.plugins
        and native.exit == native_exit
        and native_exit in (0, 1)
        and bool(failed) == (native_exit == 1)
        and not unexpected
    )
    status: ComparisonStatus = (
        "incomplete"
        if not complete
        else "failed"
        if failed
        else "complete_with_expected_skips"
        if known
        else "complete"
    )
    eligible = (
        status == "complete"
        and snapshot.graph.complete
        and snapshot.inventory.complete
        and not snapshot.provenance.gaps
        and snapshot.provenance.environment.platform == "Linux"
        and snapshot.provenance.environment.implementation == "CPython"
        and snapshot.provenance.environment.python.startswith("3.14.")
        and context.profile == "linux-py314"
        and context.event == "push"
        and context.protected
        and context.ref == "refs/heads/" + context.default_branch
        and not missed
    )
    return Comparison(
        context=context,
        snapshot_digest=snapshot.digest,
        decision_digest=decision.digest,
        status=status,
        native_exit=native_exit,
        native_cases=len(ids),
        failed_cases=failed,
        known_skips=known,
        unexpected_skips=unexpected,
        missed_failure_files=missed,
        baseline_eligible=eligible,
    )


def validate_baseline(
    baseline: Baseline, context: Context, policy_digest: str, now: int, max_age: int
) -> Snapshot:
    if (
        baseline.context.repository != context.repository
        or baseline.context.tested != context.base
        or baseline.context.profile != context.profile
        or baseline.context.default_branch != context.default_branch
        or baseline.policy_digest != policy_digest
        or not baseline.created_at <= now < baseline.expires_at
        or now - baseline.created_at > max_age
    ):
        raise ValueError("baseline identity, policy or age mismatch")
    return baseline.snapshot
