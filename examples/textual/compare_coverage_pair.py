"""Verify actual GitHub native/production-selection outcomes and advisory evidence."""

import argparse
import json
from pathlib import Path

from compare_candidate import failed
from compare_observation import junit, read, seconds

from smartci.coverage_gaps import Receipt, report
from smartci.selection import Report, digest


def compare(root, repo):
    run = json.loads(read(root / "run.json"))
    jobs = json.loads(read(root / "jobs.json"))["jobs"]
    subject = json.loads(read(root / "subject-pr.json"))
    repository = "SharmaKunal14/textual"
    if (
        run["status"] != "completed"
        or run["event"] != "pull_request"
        or run["run_attempt"] != 1
        or run["repository"]["full_name"] != repository
        or run["head_repository"]["full_name"] != repository
        or run["path"] != ".github/workflows/smartci-coverage.yml"
        or subject["head"]["sha"] != run["head_sha"]
        or subject["head"]["repo"]["full_name"] != repository
        or len(jobs) != 2
        or {j["name"] for j in jobs} != {"native", "smart"}
    ):
        raise ValueError("completed first-attempt real PR pair required")
    cases, executions, profiles, records = {}, {}, {}, {}
    for job in jobs:
        name = job["name"]
        folder = root / f"textual-{name}-1"
        execution = json.loads(read(folder / "execution.json"))
        cases[name] = junit(read(folder / "junit.xml"))
        profiles[name] = json.loads(read(folder / "profile.json"))
        if (
            execution["head"] != run["head_sha"]
            or execution["base"] != subject["base"]["sha"]
            or execution["mode"] != name
            or execution["exit_code"] not in {0, 1}
            or execution["model_calls"] != 0
            or bool(execution["exit_code"]) != bool(failed(cases[name]))
            or job["status"] != "completed"
            or job["conclusion"] != ("failure" if execution["exit_code"] else "success")
        ):
            raise ValueError("incomplete or mismatched native execution")
        executions[name] = execution
        records[name] = {
            "url": job["html_url"],
            "cases": len(cases[name]),
            "failures": sorted("::".join(k) for k in failed(cases[name])),
            "job_seconds": seconds(job["started_at"], job["completed_at"]),
            "trigger_to_result_seconds": seconds(
                run["created_at"], job["completed_at"]
            ),
            "execution": execution,
        }
    native, smart = executions["native"], executions["smart"]
    if (
        native["targets"] is not None
        or native["execution"] != "full"
        or native["planning_error"] is not None
        or profiles["native"] != profiles["smart"]
        or native["harness_sha256"] != smart["harness_sha256"]
        or smart["reporting_exit"] != 0
    ):
        raise ValueError("baseline, environment or reporting mismatch")
    folder = root / "textual-smart-1"
    selection = Report.model_validate_json(read(folder / "selection.json"))
    if selection.digest != digest(selection.model_dump(exclude={"digest"})):
        raise ValueError("selection integrity failure")
    if selection.comparison != {"base": smart["base"], "head": smart["head"]}:
        raise ValueError("selection revision mismatch")
    targets = smart["targets"]
    if targets is None:
        if selection.execution != "full" or smart["execution"] != "full":
            raise ValueError("full execution required")
        expected = set(cases["native"])
    else:
        if selection.execution != "subset" or smart["execution"] != "subset":
            raise ValueError("subset not authorized by production selector")
        expected = {
            key
            for key in cases["native"]
            if any(
                key[0] == p[:-3].replace("/", ".")
                or key[0].startswith(p[:-3].replace("/", ".") + ".")
                for p in targets
            )
        }
    if set(cases["smart"]) != expected:
        raise ValueError("executed cases differ from expected native inventory")
    gaps = json.loads(read(folder / "coverage-gaps.json"))
    proof = Receipt.model_validate_json(read(folder / "coverage-receipt.json"))
    if proof.run_url != run["html_url"] or proof.execution_scope != smart["execution"]:
        raise ValueError("coverage origin or scope mismatch")
    if proof.test_count != len(cases["smart"]) or not proof.inventory_reconciled:
        raise ValueError("coverage inventory not reconciled")
    recomputed = report(
        repo,
        repository,
        smart["base"],
        smart["head"],
        digest(profiles["smart"]),
        read(folder / "coverage.xml"),
        proof,
    )
    if gaps != recomputed:
        raise ValueError("coverage report does not reproduce from GitHub artifacts")
    missed = sorted(
        "::".join(k) for k in failed(cases["native"]) - failed(cases["smart"])
    )
    mismatch = sorted(
        "::".join(k) for k in cases["smart"] if cases["smart"][k] != cases["native"][k]
    )
    saved = (
        records["native"]["trigger_to_result_seconds"]
        - records["smart"]["trigger_to_result_seconds"]
    )
    return {
        "schema_version": "smartci.coverage-pair.v1",
        "run": run["html_url"],
        "pr": subject["html_url"],
        "base": smart["base"],
        "head": smart["head"],
        "jobs": records,
        "selected_files": len(selection.selected),
        "selection": selection.model_dump(),
        "coverage_gaps": gaps,
        "comparison": {
            "missed_native_failures": missed,
            "mismatched_selected_outcomes": mismatch,
            "matched": not missed and not mismatch,
            "smart_path_seconds_saved": saved,
            "smart_path_faster": saved > 0,
            "tests_omitted": len(cases["native"]) - len(cases["smart"]),
            "selection_benefit_demonstrated": saved > 0
            and targets is not None
            and not missed
            and not mismatch,
            "whole_validation_workflow_seconds": seconds(
                run["created_at"], run["updated_at"]
            ),
            "runner_seconds": sum(j["job_seconds"] for j in records.values()),
        },
        "limits": [
            "One pair per scenario; runner variance is not eliminated.",
            "Full-control job is validation overhead, not a deployment prerequisite of the production selector.",
            "Zero missed observed failures cannot prove unexecuted behavior correct.",
            "Coverage reporting never changes test selection; model calls remain disabled.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.artifacts, args.repo)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    raise SystemExit(0 if result["comparison"]["matched"] else 1)
