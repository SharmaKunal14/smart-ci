"""Paired native/full, native/related and Smart CI comparison on a clean revision.

Does not modify source, native configuration, test files, worker counts or caches.
Run separately on a real fix, its regression replay, and a broad upstream change.
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.discovery.commands import write_json
from smartci.git_changes import changes_from_git
from smartci.typescript.models import NativeReport, TypeScriptConfig
from smartci.typescript.native import NativeVitest, reconcile


def related(runner, changed):
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="smartci-related-") as temporary:
        output = Path(temporary) / "report.json"
        code = runner.vitest(
            [
                "related",
                *[str(runner.root / p) for p in changed],
                "--run",
                "--reporter=json",
                f"--outputFile={output}",
            ]
        )
        report = NativeReport.model_validate_json(read_bounded(output))
        observed = [runner.relative(file.name) for file in report.testResults]
        return reconcile(report, code, observed, runner, time.monotonic() - start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "repo",
        "config",
        "output",
        "node",
        "pnpm",
        "dependency-store",
        "dependency-cache",
    ):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--expect", choices=("passed", "failed"), required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    repo, output = args.repo.resolve(strict=True), args.output.resolve()
    if output.exists() or output.is_relative_to(repo):
        raise ValueError("new output directory outside the target checkout required")
    head = current_clean_head(repo)
    if head is None:
        raise ValueError("clean committed checkout required")
    config = TypeScriptConfig.model_validate_json(args.config.read_bytes())
    if config.native_project is None:
        raise ValueError("native project profile required")
    changes = changes_from_git(repo, args.base, head, config.repository)
    runner = NativeVitest(
        repo, str(args.node.resolve()), args.offline, config.native_project
    )
    output.mkdir(parents=True)
    rows, decisions = [], []
    variants = ["native_full", "smartci", "native_related"]
    for index in range(args.rounds):
        # Rotate order; do not systematically give either implementation a cold cache.
        for variant in variants[index % 3 :] + variants[: index % 3]:
            print(f"Round {index + 1}/{args.rounds}: {variant}", flush=True)
            start = time.monotonic()
            if variant == "smartci":
                destination = output / f"smartci-{index + 1}"
                command = [
                    sys.executable,
                    "-c",
                    "from smartci.cli import main; raise SystemExit(main())",
                    "typescript",
                    "run",
                    "--repo",
                    str(repo),
                    "--base",
                    args.base,
                    "--config",
                    str(args.config.resolve()),
                    "--output",
                    str(destination),
                    "--node",
                    str(args.node.resolve()),
                    "--pnpm",
                    str(args.pnpm.resolve()),
                    "--dependency-store",
                    str(args.dependency_store.resolve()),
                    "--dependency-cache",
                    str(args.dependency_cache.resolve()),
                ]
                if args.offline:
                    command.append("--offline")
                completed = subprocess.run(command, timeout=1200, check=False)
                wall = time.monotonic() - start
                run = json.loads((destination / "run.json").read_text())
                if (
                    completed.returncode != {"passed": 0, "failed": 1}[args.expect]
                    or run["status"] != args.expect
                ):
                    raise ValueError("unexpected or incomplete Smart CI result")
                decisions.append(run["decision_digest"])
                native = run["attempts"][-1]
                row = {
                    "planning_seconds": run["planning_seconds"],
                    "execution": run["execution"],
                    "fallback": run["fallback"],
                    "decision_digest": run["decision_digest"],
                    "all_attempt_failure_ids": sorted(
                        {case for a in run["attempts"] for case in a["failed_cases"]}
                    ),
                }
            else:
                result = (
                    runner.run(None, subset=False)
                    if variant == "native_full"
                    else related(runner, changes.paths)
                )
                wall = time.monotonic() - start
                native, row = result.model_dump(), {}
                if variant == "native_full" and result.status not in {
                    "passed",
                    "failed",
                }:
                    raise ValueError(f"incomplete {variant} result")
                if variant == "native_full" and result.status != args.expect:
                    raise ValueError(
                        "native ground truth disagrees with expected scenario"
                    )
            row.update(
                {
                    "round": index + 1,
                    "variant": variant,
                    "wall_seconds": wall,
                    "files": len(native["files"]),
                    "cases": native["cases"],
                    "failed": native["failed"],
                    "skipped": native["skipped"],
                    "failure_ids": native["failed_cases"],
                    "status": native["status"],
                }
            )
            rows.append(row)
            write_json(
                output / f"{variant}-{index + 1}.json",
                {"measurement": row, "native": native},
            )
            print(
                f"  {row['files']} files; {row['cases']} cases; {row['failed']} failures; {wall:.2f}s",
                flush=True,
            )
            if current_clean_head(repo) != head:
                raise ValueError("benchmark mutated tracked source")
    if len(set(decisions)) != 1:
        raise ValueError("nondeterministic Smart CI decision")
    full = [r for r in rows if r["variant"] == "native_full"]
    if any(
        r["failure_ids"] != full[0]["failure_ids"]
        or r["files"] != full[0]["files"]
        or r["cases"] != full[0]["cases"]
        for r in full
    ):
        raise ValueError("unstable native ground truth")
    for row in rows:
        row["missed_failure_ids"] = sorted(
            set(full[0]["failure_ids"])
            - set(row.get("all_attempt_failure_ids", row["failure_ids"]))
        )
        if row["variant"] == "smartci" and row["missed_failure_ids"]:
            raise ValueError(
                "Smart CI omitted failures observed by the native full suite"
            )
    medians = {
        variant: statistics.median(
            r["wall_seconds"] for r in rows if r["variant"] == variant
        )
        for variant in variants
    }
    summary = {
        "repository": config.repository,
        "base": args.base,
        "head": head,
        "changes": changes.paths,
        "profile": config.native_project.model_dump(exclude={"reviewed_skips"}),
        "rounds": args.rounds,
        "rows": rows,
        "median_wall_seconds": medians,
        "smartci_net_wall_savings_fraction": 1
        - medians["smartci"] / medians["native_full"],
        "deterministic": True,
        "limits": [
            "One native Node project and timezone, not the entire upstream CI matrix.",
            "Native cache retained; installation and runner provisioning excluded from paired timings.",
            "Smart CI includes map reconstruction and CLI startup; native related uses its own head graph.",
            "No safety guarantee follows from a finite set of observed failures.",
        ],
    }
    write_json(output / "summary.json", summary)
    print(
        json.dumps(
            {
                "medians": medians,
                "net_wall_savings_fraction": summary[
                    "smartci_net_wall_savings_fraction"
                ],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
