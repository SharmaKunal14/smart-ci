"""Shadow preparation, result comparison and isolated publication commands."""

import argparse
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

from smartci.adapters.runners import PyReport, read_bounded
from smartci.discovery.collector import collect
from smartci.discovery.commands import write_json
from smartci.discovery.models import PythonConfig, Snapshot
from smartci.discovery.planning import plan
from smartci.reports import atomic_write, markdown
from smartci.selection import Report, SelectionPolicy, digest, fallback, finish

from .github import download_baseline
from .models import Baseline, Comparison, Context, ShadowPolicy
from .shadow import compare, validate_baseline


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "shadow", help="prepare and compare shadow plans; never filter execution"
    )
    actions = parser.add_subparsers(dest="shadow_action", required=True)
    context = actions.add_parser("context")
    context.add_argument("--output", type=Path, required=True)
    for name in ("fetch", "prepare", "compare", "publish"):
        command = actions.add_parser(name)
        command.add_argument("--context", type=Path, required=True)
        command.add_argument("--policy", type=Path, required=True)
        command.add_argument("--shadow-policy", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name in {"fetch", "prepare"}:
            command.add_argument(
                "--producer-workflow", default=".github/workflows/test.yml"
            )
        if name == "prepare":
            command.add_argument("--repo", type=Path, required=True)
            command.add_argument("--python", required=True)
            command.add_argument("--config", type=Path, required=True)
            command.add_argument("--baseline", type=Path)
            command.add_argument("--force-full", action="store_true")
        if name in {"compare", "publish"}:
            command.add_argument("--snapshot", type=Path, required=True)
            command.add_argument("--decision", type=Path, required=True)
        if name == "compare":
            command.add_argument("--repo", type=Path, required=True)
            command.add_argument("--native-report", type=Path, required=True)
            command.add_argument("--native-exit", type=int, required=True)
        if name == "publish":
            command.add_argument("--comparison", type=Path, required=True)


def github_context() -> Context:
    event = json.loads(read_bounded(Path(os.environ["GITHUB_EVENT_PATH"])))
    name = os.environ["GITHUB_EVENT_NAME"]
    if name not in {"pull_request", "push", "workflow_dispatch"}:
        raise ValueError("unsupported event")
    tested = os.environ["GITHUB_SHA"]
    base = event["pull_request"]["base"]["sha"] if name == "pull_request" else tested
    return Context.model_validate(
        {
            "repository": os.environ["GITHUB_REPOSITORY"],
            "event": name,
            "run_id": int(os.environ["GITHUB_RUN_ID"]),
            "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "base": base,
            "tested": tested,
            "pr_head": event["pull_request"]["head"]["sha"]
            if name == "pull_request"
            else None,
            "ref": os.environ["GITHUB_REF"],
            "default_branch": event["repository"]["default_branch"],
            "protected": os.environ.get("GITHUB_REF_PROTECTED") == "true",
        }
    )


def command(args: argparse.Namespace) -> int:
    try:
        if args.shadow_action == "context":
            write_json(args.output, github_context().model_dump())
            return 0
        context = Context.model_validate_json(read_bounded(args.context))
        policy = SelectionPolicy.model_validate_json(read_bounded(args.policy))
        rules = ShadowPolicy.model_validate_json(read_bounded(args.shadow_policy))
        if policy.repository != context.repository or policy.mode != "shadow":
            raise ValueError("protected shadow policy required")
        policy_digest = digest(
            {"selection": policy.model_dump(), "shadow": rules.model_dump()}
        )
        now = int(time.time())
        if args.shadow_action == "fetch":
            baseline = download_baseline(context, args.producer_workflow)
            validate_baseline(
                baseline, context, policy_digest, now, rules.max_baseline_age_seconds
            )
            write_json(args.output, baseline.model_dump())
            return 0
        if args.shadow_action == "prepare":
            return prepare(args, context, policy, rules, policy_digest, now)
        snapshot = Snapshot.model_validate_json(
            read_bounded(args.snapshot, 32 * 1024 * 1024)
        )
        decision = Report.model_validate_json(read_bounded(args.decision))
        if args.shadow_action == "compare":
            native = PyReport.model_validate_json(
                read_bounded(args.native_report, 32 * 1024 * 1024)
            )
            result = compare(
                context, snapshot, decision, native, args.native_exit, rules, args.repo
            )
            write_json(args.output, result.model_dump())
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with Path(summary).open("a") as stream:
                    stream.write(
                        "## Smart CI shadow comparison\n\n"
                        f"Status: **{result.status}**. Execution: **full**.\n\n"
                        f"Native cases: {result.native_cases}; "
                        f"failed: {len(result.failed_cases)}; "
                        f"reviewed skips: {len(result.known_skips)}; "
                        f"unexpected skips: {len(result.unexpected_skips)}; "
                        f"omitted failing files: {len(result.missed_failure_files)}.\n\n"
                        f"Baseline eligible: {result.baseline_eligible}. "
                        "Selection reasons and revision bindings are in the artifacts.\n"
                    )
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "baseline_eligible": result.baseline_eligible,
                        "missed_failure_files": len(result.missed_failure_files),
                    }
                )
            )
            return (
                0
                if result.status in {"complete", "complete_with_expected_skips"}
                else 2
            )
        result = Comparison.model_validate_json(read_bounded(args.comparison))
        if (
            result.decision_digest != decision.digest
            or digest(decision.model_dump(exclude={"digest"})) != decision.digest
            or decision.execution != "full"
            or decision.evidence.get("shadow_policy") != policy_digest
            or decision.evidence.get("head_snapshot") != snapshot.digest
            or decision.comparison != {"base": context.base, "head": context.tested}
        ):
            raise ValueError("decision binding mismatch")
        baseline = Baseline(
            context=context,
            snapshot=snapshot,
            comparison=result,
            policy_digest=policy_digest,
            created_at=now,
            expires_at=now + rules.max_baseline_age_seconds,
        )
        write_json(args.output, baseline.model_dump())
        print("Eligible protected baseline written.")
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "execution": "full",
                    "code": "SHADOW_INPUT_OR_EXECUTION_ERROR",
                }
            )
        )
        return 2


def prepare(
    args: argparse.Namespace,
    context: Context,
    policy: SelectionPolicy,
    rules: ShadowPolicy,
    policy_digest: str,
    now: int,
) -> int:
    destination = args.output.resolve()
    if destination.exists() or destination.is_relative_to(args.repo.resolve()):
        raise ValueError("fresh external output directory required")
    destination.mkdir(parents=True)
    config = PythonConfig.model_validate_json(read_bounded(args.config))
    head = None
    try:
        if config.repository != context.repository:
            raise ValueError("collector repository mismatch")
        print(
            "shadow: collecting tested revision; native full execution remains independent",
            flush=True,
        )
        head, _, _ = collect(args.repo, config, args.python)
        write_json(destination / "snapshot.json", head.model_dump())
        if head.graph.commit != context.tested:
            raise ValueError("tested revision mismatch")
        if args.force_full:
            report = fallback("FORCE_FULL", head.inventory)
        else:
            try:
                baseline = (
                    Baseline.model_validate_json(
                        read_bounded(args.baseline, 32 * 1024 * 1024)
                    )
                    if args.baseline
                    else None
                )
                if baseline is None:
                    raise ValueError("baseline absent")
                base = validate_baseline(
                    baseline,
                    context,
                    policy_digest,
                    now,
                    rules.max_baseline_age_seconds,
                )
                report = plan(args.repo, base, head, policy)
                report.evidence["base_snapshot"] = base.digest
            except (OSError, ValueError):
                report = fallback(
                    "BASELINE_UNAVAILABLE_OR_INCOMPATIBLE", head.inventory
                )
    except (OSError, ValueError, RecursionError):
        report = fallback("COLLECTION_UNAVAILABLE", head.inventory if head else None)
    report.execution = "full"
    report.comparison = {"base": context.base, "head": context.tested}
    report.evidence["shadow_policy"] = policy_digest
    if head is not None:
        report.evidence["head_snapshot"] = head.digest
    finish(report)
    atomic_write(destination / "audit.md", markdown(report))
    write_json(destination / "selection.json", report.model_dump())
    write_json(destination / "context.json", context.model_dump())
    print(
        json.dumps(
            {
                "mode": report.mode,
                "execution": "full",
                "fallback": report.fallback,
                "digest": report.digest,
            }
        ),
        flush=True,
    )
    return 0
