"""Bounded, paired comparison of old/new selection and native full-suite controls."""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.discovery.commands import write_json
from smartci.selection import Report, digest
from smartci.typescript.collector import test_id
from smartci.typescript.models import NativeResult

CLI = "import sys; sys.path.insert(0, sys.argv.pop(1)); from smartci.cli import main; raise SystemExit(main())"
NATIVE = """import sys, json
from pathlib import Path
sys.path.insert(0, sys.argv.pop(1))
from smartci.typescript.native import NativeVitest
from smartci.discovery.commands import write_json
root, inventory, output, offline, defaults = sys.argv[1:]
runner = NativeVitest(Path(root), offline=offline == 'true')
if defaults == 'true':
    def native(args):
        return runner.invoke([str(Path(root)/'node_modules/vitest/vitest.mjs'), *args,
            '--config', 'vitest.config.ts', '--allowOnly=false', '--passWithNoTests=false'], timeout=600)
    runner.vitest = native
result = runner.run(json.loads(Path(inventory).read_text())['files'], subset=False)
write_json(Path(output), result.model_dump())
raise SystemExit(0 if result.status == 'passed' else 1)
"""
VARIANTS = (
    "baseline_subset",
    "candidate_subset",
    "native_bounded_full",
    "native_default_full",
)


def validate_result(directory, variant):
    data = json.loads(read_bounded(directory / "run.json"))
    if variant.endswith("subset"):
        proposal = Report.model_validate_json(
            read_bounded(directory / "selection.json")
        )
        if proposal.digest != digest(proposal.model_dump(exclude={"digest"})):
            raise ValueError("invalid decision digest")
        if (
            data["decision_digest"] != proposal.digest
            or proposal.execution != "subset"
            or proposal.mode != "subset"
            or data["execution"] != "subset"
            or data["fallback"]
            or proposal.fallback
            or not proposal.omitted
            or len(data["attempts"]) != 1
        ):
            raise ValueError(
                "benchmark requires a proper subset without retry or fallback"
            )
        result = data["attempts"][0]
        if set(proposal.selected) != {test_id(p) for p in result["files"]}:
            raise ValueError("selected/executed file mismatch")
        identity = {
            k: proposal.model_dump()[k]
            for k in ("comparison", "selected", "omitted", "reasons", "fallback")
        }
    else:
        result, identity = data, None
    NativeResult.model_validate(result)
    if (
        result["status"] != "passed"
        or result["returncode"]
        or result["failed"]
        or result["skipped"]
        or result["cases"] <= 0
        or not result["files"]
        or len(result["files"]) != len(set(result["files"]))
    ):
        raise ValueError("failed or incomplete native execution")
    return result, data, identity


def invoke(args, repo):
    start = time.monotonic()
    # NativeVitest independently removes credentials from its child environment.
    completed = subprocess.run(args, cwd=repo, check=False, timeout=720)
    elapsed = time.monotonic() - start
    if completed.returncode:
        raise ValueError("benchmark execution failed; keep its artifacts for diagnosis")
    return elapsed


def benchmark(args):
    repo, output = args.repo.resolve(strict=True), args.output.resolve()
    baseline, candidate = (
        args.baseline_tool.resolve(strict=True),
        Path(__file__).resolve().parents[1],
    )
    commit = current_clean_head(repo)
    if commit is None or output.exists() or output.is_relative_to(repo):
        raise ValueError("clean checkout and new external output directory required")
    # Both revisions must use the same Python dependency environment for a fair comparison.
    if (baseline / "uv.lock").read_bytes() != (candidate / "uv.lock").read_bytes():
        raise ValueError("benchmark tool dependency locks differ")
    output.mkdir(parents=True)
    config = candidate / "examples/onrecord/typescript.json"
    rows, decisions, digests, counts = [], {}, {}, {}
    graphs = None
    inventory = None
    for repeat in range(args.rounds):
        # Rotate positions so each variant is not always measured after the same predecessor.
        order = VARIANTS[repeat:] + VARIANTS[:repeat]
        for variant in order:
            print(f"Benchmark {repeat + 1}/{args.rounds}: {variant}", flush=True)
            destination = output / f"{repeat + 1}-{variant}"
            if variant.endswith("subset"):
                tool = baseline if variant == "baseline_subset" else candidate
                command = [
                    sys.executable,
                    "-c",
                    CLI,
                    str(tool / "src"),
                    "typescript",
                    "run",
                    "--repo",
                    str(repo),
                    "--config",
                    str(config),
                    "--base",
                    args.base,
                    "--output",
                    str(destination),
                ]
                if args.offline:
                    command.append("--offline")
            else:
                if inventory is None:
                    raise ValueError(
                        "native controls require discovered file inventory"
                    )
                destination.mkdir()
                command = [
                    sys.executable,
                    "-c",
                    NATIVE,
                    str(candidate / "src"),
                    str(repo),
                    str(inventory),
                    str(destination / "run.json"),
                    str(args.offline).lower(),
                    str(variant == "native_default_full").lower(),
                ]
            elapsed = invoke(command, repo)
            result, data, identity = validate_result(destination, variant)
            if current_clean_head(repo) != commit:
                raise ValueError("workspace changed during benchmark")
            group = "subset" if variant.endswith("subset") else "full"
            signature = (sorted(result["files"]), result["cases"])
            if group in counts and counts[group] != signature:
                raise ValueError("native file or case counts changed between variants")
            counts[group] = signature
            if identity is not None:
                observed_graphs = {
                    name: digest(json.loads(read_bounded(destination / name))["graph"])
                    for name in ("head-map.json", "base-map.json")
                }
                if graphs is not None and graphs != observed_graphs:
                    raise ValueError("optimization changed the dependency graphs")
                graphs = observed_graphs
                if decisions and identity != next(iter(decisions.values())):
                    raise ValueError("optimization changed test selection or reasons")
                decisions[variant] = identity
                decision_digest = data["decision_digest"]
                if variant in digests and digests[variant] != decision_digest:
                    raise ValueError("repeated plan was nondeterministic")
                digests[variant] = decision_digest
                inventory = destination / "head-map.json"
            rows.append(
                {
                    "round": repeat + 1,
                    "variant": variant,
                    "wall_seconds": elapsed,
                    "planning_seconds": data.get("planning_seconds", 0.0),
                    "execution_seconds": result["duration_seconds"],
                    "files": len(result["files"]),
                    "cases": result["cases"],
                }
            )
            write_json(output / "measurements.json", rows)
    medians = {
        v: {
            key: statistics.median(r[key] for r in rows if r["variant"] == v)
            for key in (
                "wall_seconds",
                "planning_seconds",
                "execution_seconds",
                "files",
                "cases",
            )
        }
        for v in VARIANTS
    }
    summary = {
        "repository_commit": commit,
        "rounds": args.rounds,
        "same_selection": True,
        "same_graphs": True,
        "deterministic_per_version": True,
        "medians": medians,
        "baseline_commit": current_clean_head(baseline),
        "candidate_commit": current_clean_head(candidate),
        "cpu_count": os.cpu_count(),
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--baseline-tool", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--offline", action="store_true")
    benchmark(parser.parse_args())


if __name__ == "__main__":
    main()
