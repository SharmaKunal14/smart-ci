"""Real native shadow comparison on the managed packaging checkout; no remote writes."""

import argparse
import os
import subprocess
import time
from pathlib import Path

from smartci.adapters.runners import PyReport
from smartci.adapters.suite import current_clean_head
from smartci.ci.commands import prepare
from smartci.ci.models import Context, ShadowPolicy
from smartci.ci.shadow import compare
from smartci.discovery.models import Snapshot
from smartci.selection import Report, SelectionPolicy, digest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "demo-output/onboarding/packaging"
EXAMPLE = ROOT / "examples/onboarding/packaging"


def main():
    repo = WORKSPACE / "repository"
    python = WORKSPACE / "environment/bin/python"
    sha = current_clean_head(repo)
    output = ROOT / "demo-output/shadow" / str(time.time_ns())
    output.mkdir(parents=True)
    ctx = Context(
        repository="pypa/packaging",
        event="workflow_dispatch",
        run_id=1,
        run_attempt=1,
        base=sha,
        tested=sha,
        ref="refs/heads/local-demo",
        default_branch="main",
        protected=False,
        profile="local-py314",
    )
    policy = SelectionPolicy.model_validate_json((EXAMPLE / "policy.json").read_bytes())
    # Reviewed source hash is pinned in the repository, not computed from the subject under test.
    rules = ShadowPolicy.model_validate_json(
        (EXAMPLE / "shadow-policy-local.json").read_bytes()
    )
    policy_hash = digest(
        {"selection": policy.model_dump(), "shadow": rules.model_dump()}
    )
    decisions = []
    for index in range(2):
        print(
            f"Plan {index + 1}/2: collecting evidence before any full execution...",
            flush=True,
        )
        args = argparse.Namespace(
            repo=repo,
            python=str(python),
            config=EXAMPLE / "config.json",
            output=output / f"plan-{index + 1}",
            force_full=False,
            baseline=None,
        )
        prepare(args, ctx, policy, rules, policy_hash, int(time.time()))
        decisions.append(
            Report.model_validate_json((args.output / "selection.json").read_bytes())
        )
    if decisions[0] != decisions[1]:
        raise RuntimeError("identical inputs produced different proposals")
    snapshot = Snapshot.model_validate_json(
        (output / "plan-1/snapshot.json").read_bytes()
    )
    print(
        "Identical proposal digests verified. Starting full native pytest ONCE (timeout 180s)...",
        flush=True,
    )
    native_path = output / "native.json"
    with (output / "native.log").open("w") as log:
        native = subprocess.run(
            [str(python), "-m", "pytest", "-p", "smartci.adapters.pytest_plugin"],
            cwd=repo,
            env={**os.environ, "SMARTCI_REPORT": str(native_path)},
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    report = PyReport.model_validate_json(native_path.read_bytes())
    result = compare(
        ctx, snapshot, decisions[0], report, native.returncode, rules, repo
    )
    (output / "comparison.json").write_text(result.model_dump_json(indent=2) + "\n")
    print(
        f"Comparison: {result.status}; cases={result.native_cases}; known skips={len(result.known_skips)}; baseline eligible={result.baseline_eligible}",
        flush=True,
    )
    print(f"Artifacts: {output}", flush=True)
    if result.status not in {"complete", "complete_with_expected_skips"}:
        raise RuntimeError("shadow comparison did not reconcile; inspect artifacts")


if __name__ == "__main__":
    main()
