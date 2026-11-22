"""Textual evaluation adapter for the general offline investigation prototype."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from benchmark import checkout, revision, selected_targets, write


def planning(args):
    from smartci.discovery.collector import collect
    from smartci.discovery.models import PythonConfig
    from smartci.discovery.planning import plan
    from smartci.git_changes import changes_from_git
    from smartci.investigation.adapters import PythonImports
    from smartci.investigation.broker import Broker
    from smartci.investigation.engine import investigate
    from smartci.investigation.models import Inputs, Limits, Location
    from smartci.investigation.replay import ImportReplay
    from smartci.selection import SelectionPolicy

    root, output = Path.cwd(), args.output
    config = PythonConfig(
        schema_version="1",
        repository="SharmaKunal14/textual",
        source_roots=["src"],
        test_roots=["tests"],
    )
    policy = SelectionPolicy(
        schema_version="1", repository=config.repository, mode="selective"
    )
    snapshots = []
    try:
        for commit in (args.base, args.head):
            print(f"Collecting native evidence at {commit}...", flush=True)
            checkout(root, commit)
            snapshot, _, _ = collect(root, config, args.target_python)
            snapshots.append(snapshot)
        base, head = snapshots
        baseline = plan(root, base, head, policy)
        if baseline != plan(root, base, head, policy):
            raise ValueError("baseline plan changed on replay")
        changes = changes_from_git(root, args.base, args.head, config.repository)
        inputs = Inputs(
            changes=changes,
            inventory=head.inventory,
            base=base.graph,
            head=head.graph,
            policy=policy,
            sources={
                s.graph.commit: {p: s.provenance.sources[p] for p in s.graph.owners}
                for s in snapshots
            },
            unresolved=sorted(
                {
                    f"{g.code}:{g.path}:{g.line}"
                    for s in snapshots
                    for g in s.provenance.gaps
                }
            ),
        )
        write(output / "investigation-input.json", inputs.model_dump())
        # Evaluation-only deterministic focus policy, not a claim of model discovery.
        paths = sorted(set(changes.paths) & set(head.graph.owners))
        paths.extend(
            sorted(
                {
                    g.path
                    for s in snapshots
                    for g in s.provenance.gaps
                    if g.path and g.path.endswith(".py") and g.path in head.graph.owners
                }
                - set(paths)
            )
        )
        locations = [
            Location(revision=s.graph.commit, path=p)
            for p in paths[:4]
            for s in snapshots
            if p in s.graph.owners
        ]
        limits = Limits(steps=32)

        def replay():
            return investigate(
                inputs,
                Broker(root, inputs, PythonImports(config.source_roots), limits),
                ImportReplay(locations),
                limits,
            )

        print("Running bounded mock investigation; no model calls...", flush=True)
        result = replay()
        if result != replay():
            raise ValueError("investigation replay not deterministic")
        final = result["final"]
        if baseline.execution == "full" and final["execution"] != "full":
            raise ValueError("investigation weakened snapshot fallback")
        if not set(baseline.selected) <= set(final["selected"]):
            raise ValueError("investigation removed baseline tests")
        write(output / "baseline-selection.json", baseline.model_dump())
        write(output / "investigation.json", result)
        write(output / "selection.json", final)
        write(
            output / "targets.json",
            sorted(head.provenance.native_targets[t] for t in final["selected"])
            if final["execution"] == "subset"
            else None,
        )
        write(
            output / "comparison.json",
            {
                "repository": config.repository,
                "base": args.base,
                "head": args.head,
                "evaluation": "rule_driven_replay_not_llm_effectiveness",
                "profile": "native Poetry locked dependencies, syntax extras, pytest tests with coverage",
                "inventory_files": len(head.inventory.tests),
                "inventory_cases": head.provenance.native_case_count,
                "native_cases_digest": head.provenance.native_cases_digest,
                "environment": head.inventory.environment,
                "baseline_selected": len(baseline.selected),
                "assisted_selected": len(final["selected"]),
                "baseline_fallback": baseline.fallback,
                "assisted_fallback": final["fallback"],
                "unresolved": len(result["unresolved"]),
                "accepted_claims": len(result["accepted_graph"]["evidence"]),
                "new_edges": sum(
                    not e["already_recorded"]
                    for e in result["accepted_graph"]["evidence"]
                ),
                "repeatable": True,
                "model_calls": 0,
                "model_effectiveness_measured": False,
            },
        )
    finally:
        checkout(root, args.head)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["plan", "run"], required=True)
    parser.add_argument("--base", type=revision, required=True)
    parser.add_argument("--head", type=revision, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--planner-python", default=sys.executable)
    parser.add_argument("--target-python", default=sys.executable)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.is_relative_to(Path.cwd()):
        parser.error("output must be outside target repository")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "plan":
        planning(args)
        return 0
    started = time.monotonic()
    targets, planning_error = None, None
    try:
        subprocess.run(
            [
                args.planner_python,
                str(Path(__file__).resolve()),
                "--mode",
                "plan",
                "--base",
                args.base,
                "--head",
                args.head,
                "--output",
                str(args.output),
                "--target-python",
                args.target_python,
            ],
            check=True,
            timeout=180,
        )
        targets = selected_targets(args.output / "targets.json")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        planning_error = type(exc).__name__
        print(
            "Investigation unavailable; running independent native full suite.",
            flush=True,
        )
    finally:
        checkout(Path.cwd(), args.head)
    planning_seconds = time.monotonic() - started
    print(f"Executing {'subset' if targets else 'full native suite'}...", flush=True)
    test_started = time.monotonic()
    command = [
        args.target_python,
        "-m",
        "pytest",
        *(targets or ["tests"]),
        "-v",
        "--cov=./src/textual",
        f"--cov-report=xml:{args.output / 'coverage.xml'}",
        "--cov-report=term-missing",
        f"--junitxml={args.output / 'junit.xml'}",
    ]
    try:
        code = subprocess.run(command, timeout=720, check=False).returncode
    except subprocess.TimeoutExpired:
        code = 124
    write(
        args.output / "execution.json",
        {
            "mode": "assisted-replay",
            "base": args.base,
            "head": args.head,
            "execution": "subset" if targets else "full",
            "targets": targets,
            "planning_error": planning_error,
            "planning_seconds": planning_seconds,
            "test_seconds": time.monotonic() - test_started,
            "command_seconds": time.monotonic() - started,
            "exit_code": code,
        },
    )
    return code if code >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
