"""Assess bounded source-read provenance from a completed native GitHub pair."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from compare_observation import compare, read


def validate_event(event, observation):
    if (
        set(event) != {"path", "context", "lifecycle", "stack", "stack_truncated"}
        or event["path"] not in observation["tracked_blobs"]
        or event["context"]
        not in {"@shared", "@other-thread", *observation["contexts"]}
        or event["lifecycle"]
        not in {
            "before_tests",
            "test_protocol",
            "between_tests",
            "after_tests",
            "session_finish",
            "other_thread",
        }
        or type(event["stack_truncated"]) is not bool
        or not 1 <= len(event["stack"]) <= 24
    ):
        raise ValueError("invalid read event")
    for frame in event["stack"]:
        if frame["family"] == "repository":
            if (
                set(frame) != {"family", "path", "line"}
                or frame["path"] not in observation["tracked_blobs"]
                or type(frame["line"]) is not int
                or not 1 <= frame["line"] <= 100_000
            ):
                raise ValueError("invalid tracked read frame")
        elif set(frame) != {"family"} or frame["family"] not in {
            "coverage",
            "pytest_cov",
            "_pytest",
            "importlib",
            "_frozen_importlib",
            "_frozen_importlib_external",
            "inspect",
            "linecache",
            "tokenize",
            "pathlib",
            "other",
        }:
            raise ValueError("invalid external read family")


def assess(root, paths, tracer_hash):
    comparison = compare(root, "observe-scoped")
    if not comparison["comparison"]["case_identities_outcomes_and_skips_equal"]:
        raise ValueError("observation changed native outcomes")
    folder = root / "textual-observe-scoped-1"
    raw = read(folder / "observation.json")
    observation = json.loads(raw)
    provenance = json.loads(read(folder / "read-provenance.json", 32 * 1024 * 1024))
    unsigned = {k: v for k, v in provenance.items() if k != "digest"}
    if (
        provenance["schema"] != "smartci.runtime-read-provenance.v1"
        or provenance["digest"]
        != hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        or provenance["observation_sha256"] != hashlib.sha256(raw).hexdigest()
        or provenance["commit"] != comparison["head"]
        or provenance["tracer_sha256"] != tracer_hash
        or provenance["omission_authorized"] is not False
        or type(provenance["completed_protocols"]) is not int
        or provenance["completed_protocols"] != observation["case_count"]
        or provenance["diagnostics"]
        or len(provenance["events"]) > 5_000
    ):
        raise ValueError("incomplete or mismatched source-read provenance")
    for event in provenance["events"]:
        validate_event(event, observation)
    for mode in ("native", "observe-scoped"):
        if comparison["jobs"][mode]["execution"].get(
            "source_read_provenance", False
        ) is not (mode == "observe-scoped"):
            raise ValueError("source-read probe execution mismatch")
    if json.loads(read(root / "textual-native-1/profile.json")) != json.loads(
        read(folder / "profile.json")
    ):
        raise ValueError("native package profiles differ")
    results = []
    for path in sorted(set(paths)):
        if path not in observation["tracked_blobs"]:
            raise ValueError("requested source outside observed tree")
        events = [e for e in provenance["events"] if e["path"] == path]
        results.append(
            {
                "path": path,
                "unique_open_records": len(events),
                "lifecycle_counts": dict(
                    sorted(Counter(e["lifecycle"] for e in events).items())
                ),
                "stack_family_counts": dict(
                    sorted(
                        Counter(
                            family
                            for e in events
                            for family in {f["family"] for f in e["stack"]}
                        ).items()
                    )
                ),
                "events": events,
            }
        )
    return {
        "schema": "smartci.runtime-read-assessment.v1",
        "comparison": comparison,
        "provenance_digest": provenance["digest"],
        "tracer_sha256": tracer_hash,
        "paths": results,
        "omission_authorized": False,
        "execution_required": "full",
        "ci_savings_demonstrated": False,
        "interpretation": "Temporal read origins only; reporting can affect CI status and must be preserved.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--tracer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assess(
        args.artifacts, args.path, hashlib.sha256(args.tracer.read_bytes()).hexdigest()
    )
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
