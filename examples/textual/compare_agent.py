"""Compare completed GitHub PR jobs; offline replay is not an LLM evaluation."""

import argparse
import json
import re
from pathlib import Path

from compare_observation import junit, read, seconds

from smartci.selection import digest


def compare(root):
    run = json.loads(read(root / "run.json"))
    jobs = json.loads(read(root / "jobs.json"))["jobs"]
    modes = {"native", "smart", "assisted-replay"}
    if (
        run["status"] != "completed"
        or run["event"] != "pull_request"
        or run["run_attempt"] != 1
        or not re.fullmatch(r"[a-f0-9]{40}", run["head_sha"])
        or len(jobs) != 3
        or {job["name"] for job in jobs} != modes
    ):
        raise ValueError("completed first-attempt three-job PR comparison required")
    records, cases, executions = {}, {}, {}
    for job in jobs:
        mode = job["name"]
        folder = root / f"textual-{mode}-1"
        execution = json.loads(read(folder / "execution.json"))
        if (
            job["status"] != "completed"
            or execution["mode"] != mode
            or execution["head"] != run["head_sha"]
            or execution["planning_error"] is not None
            or execution["execution"] != "full"
            or execution["targets"] is not None
            or type(execution["exit_code"]) is not int
            or execution["exit_code"] not in (0, 1)
            or job["conclusion"]
            != ("success" if execution["exit_code"] == 0 else "failure")
        ):
            raise ValueError("execution identity or completion mismatch")
        cases[mode] = junit(read(folder / "junit.xml"))
        failed = sorted(
            "::".join(k) for k, v in cases[mode].items() if v[0] in ("failure", "error")
        )
        if bool(failed) != bool(execution["exit_code"]):
            raise ValueError("native exit status contradicts case evidence")
        executions[mode] = execution
        records[mode] = {
            "job": job["html_url"],
            "conclusion": job["conclusion"],
            "trigger_to_result_seconds": seconds(
                run["created_at"], job["completed_at"]
            ),
            "runner_seconds": seconds(job["started_at"], job["completed_at"]),
            "planning_seconds": execution["planning_seconds"],
            "test_seconds": execution["test_seconds"],
            "cases": len(cases[mode]),
            "failures": failed,
            "execution": "full",
        }
    if len({e["base"] for e in executions.values()}) != 1 or any(
        cases[mode] != cases["native"] for mode in modes
    ):
        raise ValueError("PR comparison or native case outcomes differ")
    folder = root / "textual-assisted-replay-1"
    report = json.loads(read(folder / "investigation.json"))
    summary = json.loads(read(folder / "comparison.json"))
    static = json.loads(read(root / "textual-smart-1" / "selection.json"))
    if (
        report["digest"] != digest({k: v for k, v in report.items() if k != "digest"})
        or report["status"] != "finished"
        or report["model_calls"] != 0
        or report["model_effectiveness_measured"]
        or not summary["repeatable"]
        or summary["head"] != run["head_sha"]
        or summary["base"] != executions["native"]["base"]
        or report["final"]["comparison"]
        != {"base": summary["base"], "head": summary["head"]}
        or summary["inventory_cases"] != len(cases["native"])
        or static["selected"] != report["baseline"]["selected"]
        or static["fallback"] != report["baseline"]["fallback"]
        or not set(static["selected"]) <= set(report["final"]["selected"])
    ):
        raise ValueError("investigation provenance or baseline preservation mismatch")
    native = records["native"]["trigger_to_result_seconds"]
    return {
        "run": run["html_url"],
        "head": run["head_sha"],
        "base": summary["base"],
        "evaluation": "offline_mock_plumbing_not_llm_effectiveness",
        "jobs": records,
        "comparison": summary,
        "native_outcome_parity": True,
        "observed_missed_failures": {"smart": 0, "assisted-replay": 0},
        "fallbacks": {
            "smart": static["fallback"],
            "assisted-replay": report["final"]["fallback"],
        },
        "subset_executed": False,
        "model_calls": 0,
        "trigger_to_result_savings_seconds": {
            mode: native - records[mode]["trigger_to_result_seconds"]
            for mode in ("smart", "assisted-replay")
        },
        "total_runner_seconds": sum(r["runner_seconds"] for r in records.values()),
        "limitation": "One real regression, full execution in every arm; timing variation is not selective-test savings or LLM benefit.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(compare(args.artifacts), indent=2, sort_keys=True) + "\n"
    )
