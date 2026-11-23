"""Run paired native/candidate arms on a PR; never replace the full control."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from baseline import summarize_events
from diagnostics import PROFILE_SHA256, UPSTREAM, run_profile, targeted_profile

TOOL_ROOT = Path(__file__).resolve().parents[2]
BASELINE = TOOL_ROOT / "docs/benchmarks/abseil-apport-baseline-2026-11-23.json"
MAP_REFERENCE = TOOL_ROOT / "docs/benchmarks/abseil-graph-2026-11-23.json"
GIT = ["git", "--no-replace-objects", "-c", "core.fsmonitor=false"]


def read_bounded(path: Path, limit: int = 64 * 1024 * 1024) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("artifact exceeds bounds")
    return value


def git_output(root: Path, args: list[str], limit: int = 16 * 1024 * 1024) -> bytes:
    with tempfile.TemporaryFile() as stream:
        subprocess.run(
            [*GIT, *args],
            cwd=root,
            check=True,
            timeout=15,
            stdout=stream,
            stderr=subprocess.DEVNULL,
        )
        stream.seek(0)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Git output exceeds bounds")
    return data


def verify_checkout(root: Path, head: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("exact head commit required")
    if git_output(root, ["rev-parse", "HEAD"], 128).decode().strip() != head:
        raise ValueError("checkout does not match PR head")
    git_output(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--exit-code", head, "--"]
    )
    if git_output(root, ["ls-files", "--others", "-z"], 1):
        raise ValueError("untracked or ignored inputs present")
    raw = read_bounded(root / "ci/linux_gcc-latest_libstdcxx_bazel.sh", 128 * 1024)
    targeted_profile(raw, "full")
    # The script sources this file to choose the image; bind it independently.
    containers = "ci/linux_docker_containers.sh"
    if read_bounded(root / containers, 128 * 1024) != git_output(
        root, ["show", f"{UPSTREAM}:{containers}"], 128 * 1024
    ):
        raise ValueError("native container definition changed; review required")
    return raw


def full_plan(reason: str) -> dict[str, object]:
    return {
        "mode": "full",
        "fallback": [reason],
        "patterns": ["..."],
        "production_omission_authorized": False,
        "requires_independent_full_control": True,
    }


def plan_candidate(
    root: Path, base: str, head: str, evidence: Path
) -> dict[str, object]:
    # Lazy imports keep the independent native arm standard-library-only.
    from smartci.bazel.audit import native_inventory
    from smartci.bazel.graph import parse_query_xml
    from smartci.bazel.planning import candidate_plan, parse_tree

    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("exact base commit required")
    reference = json.loads(read_bounded(MAP_REFERENCE, 1024 * 1024))
    baseline = json.loads(read_bounded(BASELINE, 1024 * 1024))
    if (
        reference["upstream"] != UPSTREAM
        or reference["native_profile_sha256"] != PROFILE_SHA256
    ):
        raise ValueError("incompatible map reference")
    artifacts = {}
    for name in (
        "query.xml",
        "roots.txt",
        "audit.json",
        "buildfiles.txt",
        "bazel-version.txt",
    ):
        raw = read_bounded(evidence / name)
        if hashlib.sha256(raw).hexdigest() != reference["artifact_sha256"][name]:
            raise ValueError("map artifact identity mismatch")
        artifacts[name] = raw
    audit = json.loads(artifacts["audit.json"])
    if (
        audit["error"] is not None
        or audit["exit_code"] != 0
        or artifacts["bazel-version.txt"].strip() != b"bazel 9.1.0"
    ):
        raise ValueError("map is incomplete or incompatible")
    # The baseline record predates build-result retention. Reconstruct the
    # reference inventory from the authenticated raw BEP, not guessed rule kinds.
    bep = evidence.parent / "native-reference/native-resource-baseline/native.bep.json"
    if (
        hashlib.sha256(read_bounded(bep)).hexdigest()
        != baseline["artifact_sha256"]["native-resource-baseline/native.bep.json"]
    ):
        raise ValueError("native reference identity mismatch")
    native = native_inventory(summarize_events(bep))
    graph = parse_query_xml(artifacts["query.xml"])
    trees = [
        parse_tree(git_output(root, ["ls-tree", "-rz", "--full-tree", commit]))
        for commit in (UPSTREAM, base, head)
    ]
    plan = candidate_plan(
        *trees, graph, artifacts["roots.txt"].decode().splitlines(), native
    )
    plan["comparison"] = {"base": base, "head": head, "map_revision": UPSTREAM}
    plan["map_run"] = reference["run"]
    # Repeat using independently parsed bytes/trees; no timings enter the plan.
    repeat = candidate_plan(
        *[
            parse_tree(git_output(root, ["ls-tree", "-rz", "--full-tree", commit]))
            for commit in (UPSTREAM, base, head)
        ],
        parse_query_xml(artifacts["query.xml"]),
        artifacts["roots.txt"].decode().splitlines(),
        native,
    )
    if plan["digest"] != repeat["digest"]:
        raise ValueError("non-deterministic plan")
    return plan


def selected_profile(raw: bytes, subset: bool) -> bytes:
    targeted_profile(raw, "full")
    if not subset:
        return raw
    return raw.replace(
        b"/usr/local/bin/bazel test ...",
        b"/usr/local/bin/bazel test --target_pattern_file=/evidence/targets.txt",
    )


def verify_results(
    events: dict[str, object], code: int, plan: dict[str, object]
) -> list[str]:
    reference = json.loads(read_bounded(BASELINE, 1024 * 1024))
    native_tests = set(reference["native"]["bazel"]["test_targets"])
    selected = set(plan["selected"]) if plan["mode"] == "subset" else native_tests
    build_only = set(reference["build_only_labels"])
    build_results: dict[str, list[bool]] = {}
    for key, success in events["build_target_results"].items():
        label = json.loads(key)["targetCompleted"]["label"]
        build_results.setdefault(label, []).append(success)
    if set(build_results) != build_only | selected:
        raise ValueError("native build-only scope was not preserved")
    failed_tests = {label for label in selected if not any(build_results[label])}
    # A compiler failure has no testSummary when the test never ran. Account
    # for it separately; never synthesize an executed test or excuse a missing
    # outcome for a target whose build succeeded in any configuration.
    accounted = set(events["test_targets"])
    if code == 1:
        accounted |= failed_tests
    if events["exit_code"] != code or accounted != selected:
        raise ValueError("execution does not match planned native test scope")
    if any(
        not all(build_results[label]) and status != "FAILED_TO_BUILD"
        for label, status in events["test_targets"].items()
    ):
        raise ValueError("test outcome contradicts failed native build")
    if plan["mode"] == "subset":
        configurations = {}
        for key in events["build_target_results"]:
            target = json.loads(key)["targetCompleted"]
            configurations.setdefault(target["label"], []).append(
                target["configuration"]["id"]
            )
        if {name: sorted(values) for name, values in configurations.items()} != plan[
            "build_configurations"
        ]:
            raise ValueError("native build configurations were not preserved")
    elif (
        len(events["build_target_results"])
        != reference["native"]["bazel"]["build_target_configuration_count"]
    ):
        raise ValueError("native build configuration count changed")
    if code == 0 and set(events["test_targets"].values()) != {"PASSED"}:
        raise ValueError("nonpassing or flaky test outcome")
    return sorted(failed_tests)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["native", "candidate"], required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = Path.cwd().resolve(), args.output.resolve()
    if output.is_relative_to(root) or not re.fullmatch(
        r"[/._a-zA-Z0-9-]+", str(output)
    ):
        parser.error("new external output directory with simple path required")
    raw = verify_checkout(root, args.head)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    plan = full_plan("INDEPENDENT_NATIVE_CONTROL")
    if args.mode == "candidate":
        try:
            if args.evidence is None:
                raise ValueError("map evidence missing")
            plan = plan_candidate(root, args.base, args.head, args.evidence)
        except (
            ImportError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            subprocess.SubprocessError,
        ):
            plan = full_plan("MISSING_INVALID_OR_INCOMPATIBLE_MAP")
    planning_seconds = time.monotonic() - started
    (output / "plan.json").write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
    (output / "targets.txt").write_text("\n".join(plan["patterns"]) + "\n")
    profile = output / "native-profile.sh"
    profile.write_bytes(selected_profile(raw, plan["mode"] == "subset"))
    name = "smartci-evaluation-" + uuid.uuid4().hex
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if key in os.environ
    }
    environment.update(
        {
            "ABSEIL_ROOT": str(root),
            "STD": "c++17",
            "COMPILATION_MODE": "fastbuild",
            "EXCEPTIONS_MODE": "-fno-exceptions",
            "DOCKER_EXTRA_ARGS": f"--name {name} --mount type=bind,source={output},target=/evidence",
            "BAZEL_EXTRA_ARGS": "--build_event_json_file=/evidence/native.bep.json",
        }
    )
    print(
        f"Starting {args.mode}: mode={plan['mode']}; fallback={plan['fallback']}; planning={planning_seconds:.3f}s",
        flush=True,
    )
    command_started = time.monotonic()
    try:
        code, elapsed, error = run_profile(profile, output, environment, timeout=1200)
    except (OSError, ValueError, subprocess.SubprocessError):
        code, elapsed, error = (
            125,
            time.monotonic() - command_started,
            "NATIVE_COMMAND_FAILED",
        )
    if code in {124, 125} or code < 0:
        try:
            subprocess.run(
                ["docker", "rm", "--force", name],
                check=True,
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            error = "NATIVE_CONTAINER_CLEANUP_FAILED"
    events = None
    failed_test_build_targets: list[str] = []
    try:
        events = summarize_events(output / "native.bep.json")
        failed_test_build_targets = verify_results(events, code, plan)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        error = error or "EXECUTION_EVIDENCE_INVALID"
    report = {
        "schema_version": "smartci.native-paired-evaluation.v1",
        "arm": args.mode,
        "base": args.base,
        "head": args.head,
        "native_profile_sha256": PROFILE_SHA256,
        "executed_profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "planning_seconds": planning_seconds,
        "command_seconds": elapsed,
        "process_seconds": time.monotonic() - started,
        "exit_code": code,
        "evidence_error": error,
        "bazel": events,
        "failed_test_build_targets": failed_test_build_targets,
        "model_calls": 0,
        "production_omission_authorized": False,
        "requires_independent_full_control": True,
    }
    (output / "execution.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "arm",
                    "exit_code",
                    "evidence_error",
                    "failed_test_build_targets",
                    "process_seconds",
                )
            }
        ),
        flush=True,
    )
    return code if code > 0 else 1 if code < 0 or error else 0


if __name__ == "__main__":
    raise SystemExit(main())
