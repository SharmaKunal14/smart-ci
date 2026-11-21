"""CLI boundary for trusted local collection and conservative snapshot planning."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from smartci.adapters.results import RunReport
from smartci.adapters.runners import read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.reports import atomic_write, markdown
from smartci.selection import SelectionPolicy, digest, fallback

from .collector import collect
from .models import PythonConfig, Snapshot
from .planning import plan


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def collect_command(args: argparse.Namespace) -> int:
    try:
        config = PythonConfig.model_validate_json(read_bounded(args.config))
        root = args.repo.resolve(strict=True)
        destination = args.output.resolve()
        if (
            destination.is_relative_to(root)
            or destination.exists()
            or args.config.resolve().is_relative_to(destination)
        ):
            raise ValueError("new output directory outside repository required")
        snapshot, runner, units = collect(root, config, args.python)
        destination.mkdir(parents=True)
        write_json(destination / "inventory.json", snapshot.inventory.model_dump())
        write_json(destination / "graph.json", snapshot.graph.model_dump())
        write_json(destination / "provenance.json", snapshot.provenance.model_dump())
        # Publish the self-contained, digest-checked bundle last.
        write_json(destination / "snapshot.json", snapshot.model_dump())
        status = "collected" if snapshot.graph.complete else "full_required"
        exitcode = 0
        if args.run_full:
            result = runner.run(units)
            if current_clean_head(root) != snapshot.graph.commit:
                raise ValueError("workspace changed during execution")
            full = RunReport.model_validate(
                {
                    "schema_version": "1",
                    "repository": config.repository,
                    "status": result.status,
                    "execution": "full",
                    "fallback": [],
                    "inventory_digest": digest(snapshot.inventory.model_dump()),
                    "decision_digest": None,
                    "attempts": [
                        {
                            "suite": "pytest",
                            "mode": "full",
                            "targets": {u.id: u.target for u in units},
                            **asdict(result),
                        }
                    ],
                }
            )
            write_json(destination / "native-results.json", runner.native_results)
            write_json(destination / "full-run.json", full.model_dump())
            status = result.status
            exitcode = {"passed": 0, "failed": 1, "incomplete": 2}[result.status]
        print(
            json.dumps(
                {
                    "status": status,
                    "units": len(units),
                    "native_cases": snapshot.provenance.native_case_count,
                    "gaps": sorted({g.code for g in snapshot.provenance.gaps}),
                    "snapshot": snapshot.digest,
                }
            )
        )
        return exitcode
    except (OSError, ValueError, RecursionError):
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "code": "COLLECTION_OR_OUTPUT_ERROR",
                    "execution": "full",
                }
            )
        )
        return 2


def plan_command(args: argparse.Namespace) -> int:
    head = None
    try:
        head = Snapshot.model_validate_json(
            read_bounded(args.head_snapshot, 32 * 1024 * 1024)
        )
        base = Snapshot.model_validate_json(
            read_bounded(args.base_snapshot, 32 * 1024 * 1024)
        )
        policy = SelectionPolicy.model_validate_json(read_bounded(args.policy))
        report = plan(args.repo, base, head, policy)
    except (OSError, ValueError, RecursionError):
        report = fallback(
            "INVALID_OR_UNAVAILABLE_SNAPSHOT", head.inventory if head else None
        )
    try:
        inputs = {
            p.resolve() for p in [args.head_snapshot, args.base_snapshot, args.policy]
        }
        outputs = {args.output.resolve(), args.audit.resolve()}
        if (
            len(outputs) != 2
            or inputs & outputs
            or any(p.is_relative_to(args.repo.resolve()) for p in outputs)
        ):
            raise ValueError("output aliases repository or input")
        atomic_write(args.audit, markdown(report))
        write_json(args.output, report.model_dump())
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "code": "PLAN_WRITE_FAILED",
                    "execution": "full",
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "mode": report.mode,
                "execution": report.execution,
                "fallback": report.fallback,
                "digest": report.digest,
            }
        )
    )
    return 0
