"""One bounded model trial against pinned evidence from real Textual PR #11."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.commands import command
from smartci.investigation.engine import investigate
from smartci.investigation.models import Inputs, Limits, Location
from smartci.investigation.replay import ImportReplay
from smartci.reports import atomic_write

INPUT_SHA256 = "e8188837095af250f14c13f312c226c745e7f64751a4fb922664d1af034a099b"
BASE = "ae23055a7898901a3aa69229bf9359b110be739e"
HEAD = "b99f72e9691c85f18fd773df427cb5e7a493470d"


def prepare(path: Path) -> Inputs:
    raw = read_bounded(path, 32 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA256:
        raise ValueError("hosted input artifact changed")
    inputs = Inputs.model_validate_json(raw)
    if (inputs.base.commit, inputs.head.commit) != (BASE, HEAD):
        raise ValueError("unexpected Textual revisions")
    # Explicit opt-in for the approved public-code experiment. No selection
    # policy, source map, unknown or graph relationship is changed.
    inputs.policy.allow_source_excerpts = True
    return Inputs.model_validate_json(inputs.model_dump_json())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = prepare(args.artifact)
    bound_input = args.output / "input.json"
    atomic_write(bound_input, inputs.model_dump_json())
    focus = "src/textual/_xterm_parser.py"
    limits = Limits(steps=4, seconds=120)
    replay = investigate(
        inputs,
        Broker(args.repo, inputs, PythonImports(["src"]), limits),
        ImportReplay([Location(revision=HEAD, path=focus)]),
        limits,
    )
    atomic_write(args.output / "replay.json", json.dumps(replay, sort_keys=True))
    print("Starting one admitted public-source trial; at most four calls.", flush=True)
    code = command(
        argparse.Namespace(
            inputs=bound_input,
            repo=args.repo,
            module_root=["src"],
            focus=[focus],
            output=args.output / "live.json",
            provider="openai",
            campaign="textual-public-20261123",
            budget_repository="SharmaKunal14/smart-ci",
            budget_branch="codex/model-budget-textual-public-20261123",
            trial=1,
            data_scope="public-github-global-openai",
        )
    )
    live_path = args.output / "live.json"
    live = (
        json.loads(read_bounded(live_path, 64 * 1024 * 1024))
        if live_path.exists()
        else None
    )
    result = {
        "schema_version": "smartci.live-trial.v1",
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "workflow_sha": os.environ["GITHUB_SHA"],
        "source_run": "https://github.com/SharmaKunal14/textual/actions/runs/45058699772",
        "source_pr": "https://github.com/SharmaKunal14/textual/pull/11",
        "source_input_sha256": INPUT_SHA256,
        "trial_input_digest": inputs.identity(),
        "base": BASE,
        "head": HEAD,
        "trial": 1,
        "live_exit": code,
        "live_status": live["status"] if live else "no_report",
        "live_accounting": live["accounting"] if live else None,
        "replay_status": replay["status"],
        "test_execution": "none; this measures investigation only",
        "speedup_demonstrated": False,
    }
    for name, report in (("live", live), ("replay", replay)):
        if report is not None:
            edges = report["accepted_graph"]["evidence"]
            result[name + "_new_edges"] = sum(not e["already_recorded"] for e in edges)
            result[name + "_accepted"] = len(edges)
            result[name + "_unresolved"] = len(report["unresolved"])
            result[name + "_execution"] = report["final"]["execution"]
            if report["final"]["execution"] != "full":
                raise ValueError("Textual unknowns must preserve full execution")
    atomic_write(args.output / "summary.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
