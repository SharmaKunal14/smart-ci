"""Audit a new evidence tool against captured real Textual PR #11 inputs.

This reads pinned Git blobs only. It neither executes Textual nor measures CI
speedup or model effectiveness. The production adapter contains no pilot paths.
"""

import argparse
import hashlib
import json
import os
from collections import defaultdict, deque
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.engine import investigate
from smartci.investigation.models import Inputs, Limits, Location
from smartci.investigation.process_scripts import PythonProcessScripts
from smartci.investigation.replay import DiagnosticReplay, ImportReplay
from smartci.reports import atomic_write

INPUT_SHA256 = "e8188837095af250f14c13f312c226c745e7f64751a4fb922664d1af034a099b"
BASE = "ae23055a7898901a3aa69229bf9359b110be739e"
HEAD = "b99f72e9691c85f18fd773df427cb5e7a493470d"
PARENT = "tests/test_pipe.py"
CHILD = "tests/deadlock.py"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reachable_tests(graph, paths):
    reverse = defaultdict(set)
    for source, targets in graph["dependencies"].items():
        for target in targets:
            reverse[target].add(source)
    reached = {graph["owners"][path] for path in paths}
    pending = deque(sorted(reached))
    while pending:
        for source in sorted(reverse[pending.popleft()] - reached):
            reached.add(source)
            pending.append(source)
    return sorted(test for test, owner in graph["tests"].items() if owner in reached)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = read_bounded(args.artifact, 32 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == INPUT_SHA256, "input artifact changed")
    inputs = Inputs.model_validate_json(raw)
    require(
        (inputs.base.commit, inputs.head.commit) == (BASE, HEAD),
        "unexpected source revisions",
    )
    original = inputs.model_dump_json()
    args.output.mkdir(parents=True, exist_ok=False)
    print("Checking import-only control and registered process evidence.", flush=True)

    def run(process):
        limits = Limits()
        broker = Broker(
            args.repo,
            inputs,
            PythonImports(["src"]),
            limits,
            additional_adapters=(PythonProcessScripts(),) if process else (),
        )
        provider = (
            DiagnosticReplay()
            if process
            else ImportReplay(
                [Location(revision=revision, path=PARENT) for revision in (BASE, HEAD)]
            )
        )
        return investigate(inputs, broker, provider, limits)

    control, candidate, repeated = run(False), run(True), run(True)
    for name, report in (("control", control), ("candidate", candidate)):
        atomic_write(args.output / f"{name}.json", json.dumps(report, sort_keys=True))
        require(report["status"] == "finished", "investigation did not finish")
        require(report["model_calls"] == 0, "unexpected model accounting")
        require(report["unresolved"] == sorted(inputs.unresolved), "gaps changed")
        require(report["final"]["execution"] == "full", "full fallback was lost")
        require(
            report["final"]["fallback"] == ["INCOMPLETE_EVIDENCE"],
            "fallback reason changed",
        )
    require(candidate == repeated, "identical inputs did not reproduce the report")
    require(inputs.model_dump_json() == original, "input data mutated")
    require(not control["accepted_graph"]["evidence"], "unexpected control evidence")
    evidence = candidate["accepted_graph"]["evidence"]
    require(len(evidence) == 2, "expected one new edge at each revision")
    require({edge["revision"] for edge in evidence} == {BASE, HEAD}, "revision missing")
    for edge in evidence:
        require(
            (edge["path"], edge["target"], edge["line"], edge["already_recorded"])
            == (PARENT, CHILD, 16, False),
            "unexpected process relationship",
        )
        require(
            edge["verifier"] == "python-process-script-v1"
            and edge["relation"] == "python_process_script_argument"
            and edge["source_digest"] == inputs.sources[edge["revision"]][PARENT],
            "evidence identity mismatch",
        )
    reachability = {}
    for side in ("base", "head"):
        before = getattr(inputs, side).model_dump()
        expected = getattr(inputs, side).model_dump()
        owner, target = before["owners"][PARENT], before["owners"][CHILD]
        require(target not in before["dependencies"][owner], "edge was already present")
        expected["dependencies"][owner] = sorted(
            set(expected["dependencies"][owner]) | {target}
        )
        after = candidate["accepted_graph"][side]
        require(after == expected, "graph changed beyond the verified positive edge")
        reachability[side] = {
            "before": len(reachable_tests(before, inputs.changes.paths)),
            "after": len(reachable_tests(after, inputs.changes.paths)),
        }
    require(
        candidate["final"]["selected"] == control["final"]["selected"],
        "fallback selection changed",
    )
    result = {
        "schema_version": "smartci.process-evidence-audit.v1",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "workflow_sha": os.environ.get("GITHUB_SHA"),
        "source_pr": "https://github.com/SharmaKunal14/textual/pull/11",
        "source_run": "https://github.com/SharmaKunal14/textual/actions/runs/45058699772",
        "source_input_sha256": INPUT_SHA256,
        "input_digest": inputs.identity(),
        "base": BASE,
        "head": HEAD,
        "control_new_edges": 0,
        "candidate_new_versioned_edges": len(evidence),
        "unique_relationships": [[PARENT, CHILD]],
        "known_graph_reachability": reachability,
        "candidate_digest": candidate["digest"],
        "deterministic_replay": True,
        "unresolved_preserved": len(inputs.unresolved),
        "selected_test_files": len(candidate["final"]["selected"]),
        "execution": "full",
        "fallback": candidate["final"]["fallback"],
        "model_calls": 0,
        "test_execution": "none; source-only investigation audit",
        "speedup_demonstrated": False,
        "model_effectiveness_measured": False,
    }
    atomic_write(args.output / "summary.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
