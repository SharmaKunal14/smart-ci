"""Reconcile a shadow candidate against its mandatory full GitHub control."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from compare_observation import junit, read, seconds
from runtime_candidate import REPOSITORY, enrollment


def failed(cases):
    return {key for key, value in cases.items() if value[0] in {"failure", "error"}}


def compare(root, seed, *, mode="candidate", subject_head=None):
    if mode not in {"candidate", "agent"}:
        raise ValueError("invalid measurement arm")
    focused = subject_head is not None
    run = json.loads(read(root / "run.json"))
    jobs = json.loads(read(root / "jobs.json"))["jobs"]
    expected_jobs = (
        {"native", "candidate", "agent"} if focused else {"native", "candidate"}
    )
    if len(jobs) != len(expected_jobs) or {j["name"] for j in jobs} != expected_jobs:
        raise ValueError("required native and experimental jobs missing")
    jobs = [j for j in jobs if j["name"] in {"native", mode}]
    expected_repository = "SharmaKunal14/smart-ci" if focused else REPOSITORY
    expected_workflow = (
        ".github/workflows/textual-runtime-comparison.yml"
        if focused
        else ".github/workflows/smartci-pilot.yml"
    )
    head = subject_head or run["head_sha"]
    if (
        run["repository"]["full_name"] != expected_repository
        or run["head_repository"]["full_name"] != expected_repository
        or run["path"] != expected_workflow
        or run["status"] != "completed"
        or run["event"] != "pull_request"
        or run["run_attempt"] != 1
        or not re.fullmatch(r"[a-f0-9]{40}", run["head_sha"])
        or not re.fullmatch(r"[a-f0-9]{40}", head)
    ):
        raise ValueError("completed first-attempt candidate PR pair required")
    outcomes, executions, timing, profiles = {}, {}, {}, {}
    candidate_mode = mode
    for job in jobs:
        mode = job["name"]
        folder = root / f"textual-{mode}-1"
        execution = json.loads(read(folder / "execution.json"))
        if (
            job["status"] != "completed"
            or execution["head"] != head
            or execution["mode"] != mode
            or execution["required_execution"] != "full"
            or execution["omission_authorized"] is not False
            or type(execution["exit_code"]) is not int
            or execution["exit_code"] not in {0, 1}
            or job["conclusion"]
            != ("success" if execution["exit_code"] == 0 else "failure")
        ):
            raise ValueError("native execution identity or completion mismatch")
        raw = read(folder / "junit.xml")
        outcomes[mode] = junit(raw)
        executions[mode] = execution
        profiles[mode] = json.loads(read(folder / "profile.json"))
        if bool(failed(outcomes[mode])) != bool(execution["exit_code"]):
            raise ValueError("exit status contradicts native cases")
        timing[mode] = {
            "url": job["html_url"],
            "id": job["id"],
            "conclusion": job["conclusion"],
            "cases": len(outcomes[mode]),
            "failed_cases": sorted("::".join(k) for k in failed(outcomes[mode])),
            "job_seconds": seconds(job["started_at"], job["completed_at"]),
            "trigger_to_result_seconds": seconds(
                run["created_at"], job["completed_at"]
            ),
            "queue_seconds": seconds(run["created_at"], job["started_at"]),
            "junit_sha256": hashlib.sha256(raw).hexdigest(),
            "execution": execution,
        }
    mode = candidate_mode
    native, selected = executions["native"], executions[mode]
    if (
        native["execution"] != "full"
        or native["targets"] is not None
        or native["planning_error"] is not None
        or native["base"] != selected["base"]
        or profiles["native"] != profiles[mode]
        or native["harness_sha256"] != selected["harness_sha256"]
    ):
        raise ValueError("native control or environment differs")
    seed_report = enrollment(seed, native["base"], profiles["native"])
    seeded_cases = junit(read(seed / "textual-native-1/junit.xml"))
    full, subset = outcomes["native"], outcomes[mode]
    if full.keys() != seeded_cases.keys():
        raise ValueError("native inventory changed since enrollment")
    candidate = None
    targets = selected["targets"]
    if targets is None:
        if selected["execution"] != "full":
            raise ValueError("missing subset targets")
        expected = set(full)
    else:
        candidate = json.loads(read(root / f"textual-{mode}-1/candidate.json"))
        unsigned = {k: v for k, v in candidate.items() if k != "digest"}
        if (
            candidate["schema_version"] != "smartci.runtime-shadow-candidate.v1"
            or candidate["digest"]
            != hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            or candidate["comparison"]
            != {"base": native["base"], "head": native["head"]}
            or candidate["observation_digest"] != seed_report["observation_digest"]
            or candidate["omission_authorized"] is not False
            or candidate["required_execution"] != "full"
            or candidate["candidate_files"] != targets
            or not targets
            or candidate["fallback"]
            or selected["planning_error"] is not None
            or selected["execution"] != "subset"
        ):
            raise ValueError("candidate provenance or execution mismatch")
        expected = set()
        for path in targets:
            if not re.fullmatch(
                r"tests/[A-Za-z0-9_./-]+\.py", path
            ) or ".." in path.split("/"):
                raise ValueError("invalid candidate target")
            prefix = path[:-3].replace("/", ".")
            matched = {
                k for k in full if k[0] == prefix or k[0].startswith(prefix + ".")
            }
            if not matched:
                raise ValueError("selected file has no native cases")
            expected.update(matched)
    if set(subset) != expected:
        raise ValueError("executed cases differ from selected native files")
    mismatches = sorted("::".join(k) for k in subset if subset[k] != full[k])
    missed = sorted("::".join(k) for k in failed(full) - failed(subset))
    potential = (
        timing["native"]["trigger_to_result_seconds"]
        - timing[mode]["trigger_to_result_seconds"]
    )
    return {
        "run": run["html_url"],
        "head": head,
        "tool_revision": run["head_sha"] if focused else None,
        "jobs": timing,
        "enrollment_run": seed_report["run"],
        "candidate": candidate,
        "comparison": {
            "mismatched_selected_cases": mismatches,
            "missed_native_failures": missed,
            "identical_selected_outcomes_and_no_missed_failures": not mismatches
            and not missed,
            "candidate_feedback_seconds_saved": potential,
            "candidate_feedback_faster": potential > 0,
            "total_runner_seconds": sum(j["job_seconds"] for j in timing.values()),
            "whole_workflow_seconds": seconds(run["created_at"], run["updated_at"]),
            "production_selective_savings_demonstrated": False,
        },
        "limits": [
            "full native control remains mandatory; candidate is a shadow hypothesis",
            "one comparison cannot establish dependency completeness or average speedup",
            "unobserved paths, shared state, source readers and background work remain unresolved",
            "enrollment cost is separate and must be amortized; setup and download included in job timing",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.artifacts, args.enrollment)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return (
        0
        if result["comparison"]["identical_selected_outcomes_and_no_missed_failures"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
