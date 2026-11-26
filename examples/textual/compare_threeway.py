"""Separate runtime selection effects from the incremental live-agent contribution."""

import argparse
import hashlib
import json
from pathlib import Path

from compare_candidate import compare
from compare_observation import read


def identity(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def signed(path):
    value = json.loads(read(path))
    if value["digest"] != identity({k: v for k, v in value.items() if k != "digest"}):
        raise ValueError("artifact integrity mismatch")
    return value


def reconcile(root, seed):
    subject = json.loads(read(root / "subject-pr.json"))
    if (
        subject["head"]["repo"]["full_name"] != "SharmaKunal14/textual"
        or subject["merged"]
    ):
        raise ValueError("unmerged Textual source PR required")
    head = subject["head"]["sha"]
    deterministic = compare(root, seed, subject_head=head)
    assisted = compare(root, seed, mode="agent", subject_head=head)
    if deterministic["jobs"]["native"]["execution"]["base"] != subject["base"]["sha"]:
        raise ValueError("source PR comparison mismatch")
    initial = signed(root / "textual-agent-1/initial-candidate.json")
    candidate = signed(root / "textual-candidate-1/candidate.json")
    if initial != candidate:
        raise ValueError("agent and deterministic arm started with different evidence")
    report = signed(root / "textual-agent-1/agent.json")
    inputs = json.loads(read(root / "textual-agent-1/agent-input.json"))
    if (
        report["input_digest"] != identity(inputs)
        or report["final"]["execution"] != "full"
    ):
        raise ValueError("agent input or production fallback mismatch")
    if (
        report["provider"] != "openai:gpt-6.2-astra"
        or report["evaluation_kind"] != "live_model_observation"
        or type(report["model_calls"]) is not int
        or not 1 <= report["model_calls"] <= 4
        or report["model_calls"] != report["accounting"]["model_calls"]
    ):
        raise ValueError(
            "completed real-model calls required; replay is not model evidence"
        )
    agent_plan = signed(root / "textual-agent-1/candidate.json")
    if (
        agent_plan["initial_candidate_digest"] != initial["digest"]
        or agent_plan["investigation_digest"] != report["digest"]
    ):
        raise ValueError("agent candidate not bound to investigation")
    before, after = (
        set(candidate["candidate_files"]),
        set(agent_plan["candidate_files"]),
    )
    if not before <= after:
        raise ValueError("agent removed deterministic required tests")
    timing = json.loads(read(root / "textual-agent-1/agent-timing.json"))
    jobs = deterministic["jobs"] | {"agent": assisted["jobs"]["agent"]}
    return {
        "schema_version": "smartci.three-arm-runtime-evaluation.v1",
        "run": deterministic["run"],
        "source_pr": subject["html_url"],
        "source_head": head,
        "tool_revision": deterministic["tool_revision"],
        "enrollment_run": deterministic["enrollment_run"],
        "jobs": jobs,
        "deterministic": deterministic["comparison"],
        "assisted": assisted["comparison"],
        "agent_increment": {
            "status": report["status"],
            "accounting": report["accounting"],
            "timing": timing,
            "accepted_new_edges": sum(
                not e["already_recorded"] for e in report["accepted_graph"]["evidence"]
            ),
            "additional_test_files": sorted(after - before),
            "feedback_seconds_added": jobs["agent"]["trigger_to_result_seconds"]
            - jobs["candidate"]["trigger_to_result_seconds"],
            "cases_added": jobs["agent"]["cases"] - jobs["candidate"]["cases"],
            "native_failures_recovered": sorted(
                set(deterministic["comparison"]["missed_native_failures"])
                - set(assisted["comparison"]["missed_native_failures"])
            ),
        },
        "total_runner_seconds": sum(j["job_seconds"] for j in jobs.values()),
        "production_selective_savings_demonstrated": False,
        "candidate_digest": candidate["digest"],
        "agent_report_digest": report["digest"],
        "limits": [
            "one real regression, not a representative average or safety proof",
            "experimental subsets retain independent authoritative full control",
            "agent is addition-only and cannot reduce the deterministic candidate",
            "runtime savings cannot be attributed to the model",
            "clock begins at Smart CI evaluation workflow creation; automatic Textual PR trigger latency is not measured",
            "runner variance and separate one-time enrollment cost remain",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.artifacts, args.enrollment)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return (
        0
        if all(
            result[arm]["identical_selected_outcomes_and_no_missed_failures"]
            for arm in ("deterministic", "assisted")
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
