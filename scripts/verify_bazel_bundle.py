"""Verify portable CLI plans against immutable real-PR captures on GitHub.

This does not execute Abseil tests or measure performance. Native results remain
the independently recorded hosted runs, never this verifier's own assertions.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from smartci.bazel.bundle import Profile, canonical, read_bounded, sha256
from smartci.bazel.commands import revision_tree
from smartci.bazel.planning import changed_paths, parse_tree

TOOL = Path(__file__).resolve().parents[1]
ANCHOR = "434d2a068d1e6690a38a1a63d565f915f39bc4fb"
NATIVE_HEAD = "6da46d213f16f99b80f57f9d861792bb793923a9"
PROFILE = "03239a4a9294eecfa5270d397cb0250824f8930e6dcc42c4fe37955ae0c2ade1"
IMAGE = "gcr.io/google.com/absl-177019/linux_hybrid-latest@sha256:baa99e65a3cc837bab8e5246f1870d25c76d0adf2b1d598ee5a3ec77fd2e19bd"


def document(path):
    return json.loads(read_bounded(path, 1024 * 1024))


def cli(*arguments):
    result = subprocess.run(
        ["smartci", "bazel", *map(str, arguments)],
        check=True,
        timeout=60,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def checkout(repo, revision):
    subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            "checkout",
            "--quiet",
            "--detach",
            revision,
        ],
        check=True,
        timeout=30,
    )


def verify_provenance(root, kind, head, workflow, run_id):
    run = document(root / (kind + "-run.json"))
    expected = {
        "id": run_id,
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        "run_attempt": 1,
        "path": ".github/workflows/" + workflow,
    }
    if run["repository"]["full_name"] != "SharmaKunal14/abseil-cpp" or any(
        run.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("capture provenance mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.repo.resolve()) or output.is_relative_to(
        args.capture.resolve()
    ):
        raise ValueError("verification output overlaps inputs")
    output.mkdir(exist_ok=False)
    verify_provenance(
        args.capture, "graph", ANCHOR, "smartci-native-query.yml", 45083836757
    )
    verify_provenance(
        args.capture,
        "native",
        NATIVE_HEAD,
        "smartci-resource-baseline.yml",
        45073921737,
    )
    # The query and full test captures used different PRs. Only the query
    # workflow was added; require identical application/build/test inputs.
    differences = changed_paths(
        parse_tree(revision_tree(args.repo, ANCHOR)),
        parse_tree(revision_tree(args.repo, NATIVE_HEAD)),
    )
    if differences != [".github/workflows/smartci-native-query.yml"]:
        raise ValueError("graph and native captures have different source inputs")
    graph = args.capture / "native-query"
    bep = args.capture / "native-reference/native-resource-baseline/native.bep.json"
    reference = document(TOOL / "docs/benchmarks/abseil-graph-2026-11-23.json")
    native = document(TOOL / "docs/benchmarks/abseil-apport-baseline-2026-11-23.json")
    for name in [
        "query.xml",
        "roots.txt",
        "audit.json",
        "bazel-version.txt",
        "buildfiles.txt",
    ]:
        if (
            sha256(read_bounded(graph / name, 64 * 1024 * 1024))
            != reference["artifact_sha256"][name]
        ):
            raise ValueError("graph capture identity mismatch")
    native_bytes = read_bounded(bep, 64 * 1024 * 1024)
    if (
        sha256(native_bytes)
        != native["artifact_sha256"]["native-resource-baseline/native.bep.json"]
    ):
        raise ValueError("native capture identity mismatch")
    start = json.loads(native_bytes.splitlines()[0])["started"]
    profile = Profile(
        schema_version="1",
        repository="SharmaKunal14/abseil-cpp",
        bazel_version="9.1.0",
        command_digest=PROFILE,
        options_digest=sha256(start["optionsDescription"].encode()),
        environment_digest=sha256(
            canonical(
                {
                    "STD": "c++17",
                    "COMPILATION_MODE": "fastbuild",
                    "EXCEPTIONS_MODE": "-fno-exceptions",
                    "runner": "ubuntu-24.04",
                    "container": IMAGE,
                    "runner_policy": "systemd-no-storage-apport-masked",
                }
            )
        ),
        query_mode="unconfigured-deps-all",
        change_model="reviewed-declared-cpp-inputs-v1",
    )
    profile_path = output / "profile.json"
    profile_path.write_bytes(canonical(profile.model_dump()))
    checkout(args.repo, ANCHOR)
    bundle = output / "bundle"
    receipt = cli(
        "pack",
        "--repo",
        args.repo,
        "--revision",
        ANCHOR,
        "--profile",
        profile_path,
        "--query",
        graph / "query.xml",
        "--roots",
        graph / "roots.txt",
        "--native-bep",
        bep,
        "--output",
        bundle,
    )
    digest = receipt["manifest_digest"]
    recorded = document(TOOL / "docs/benchmarks/abseil-single-workflow-2026-11-23.json")
    regression = document(TOOL / "docs/benchmarks/abseil-regression-2026-11-23.json")
    shared = document(TOOL / "docs/benchmarks/abseil-shared-hash-2026-11-23.json")
    expected_labels = {
        "localized": recorded["results"]["candidate"]["selected"],
        "regression": regression["arms"]["candidate"]["failed_test_build_targets"],
        "shared": sorted(shared["arms"]["candidate"]["test_targets"]),
        "build-change": sorted(recorded["results"]["native"]["test_targets"]),
    }
    configurations = {}
    for key in recorded["results"]["native"]["build_target_results"]:
        target = json.loads(key)["targetCompleted"]
        configurations.setdefault(target["label"], []).append(
            target["configuration"]["id"]
        )
    results = []
    for name, base, head, expected, fallback in [
        (
            "localized",
            "6caf49f391bac80d83d81ad925cd29ae75872f3e",
            "2745f8c71cfe5e04081b68e3cab6bea4fab069e6",
            2,
            [],
        ),
        (
            "regression",
            "ea6b613a408b2f7198562626bd7e357e1064ef35",
            "1174e91618f3447b60727afbc075ae3b084beedf",
            2,
            [],
        ),
        (
            "shared",
            "b00426ab4fc1725a6499a6f112e5fdd63fd2cd94",
            "813567330d3671d9da4a2fecd36b398e5b0a599a",
            251,
            [],
        ),
        (
            "build-change",
            "2745f8c71cfe5e04081b68e3cab6bea4fab069e6",
            "2d5a7985bfe983dc080a5dd62db3fdf203f526ff",
            252,
            ["MAP_INPUTS_CHANGED", "UNSUPPORTED_OR_RISK_CHANGE"],
        ),
    ]:
        checkout(args.repo, head)
        arguments = [
            "plan",
            "--repo",
            args.repo,
            "--base",
            base,
            "--head",
            head,
            "--profile",
            profile_path,
            "--bundle",
            bundle,
            "--expected-digest",
            digest,
            "--execution-mode",
            "selective",
        ]
        paths = [output / (name + suffix) for suffix in [".json", ".repeat.json"]]
        for path in paths:
            cli(*arguments, "--output", path)
        if paths[0].read_bytes() != paths[1].read_bytes():
            raise ValueError("non-deterministic CLI plan")
        plan = document(paths[0])
        if (
            len(plan["selected"]) != expected
            or plan["fallback"] != fallback
            or len(plan["build_only"]) != 324
        ):
            raise ValueError("real-PR scope mismatch")
        if plan["selected"] != sorted(expected_labels[name]) or plan[
            "build_only"
        ] != sorted(native["build_only_labels"]):
            raise ValueError("planned identities differ from recorded native outcomes")
        expected_configurations = {
            label: sorted(configurations[label])
            for label in plan["selected"] + plan["build_only"]
        }
        if plan["build_configurations"] != expected_configurations:
            raise ValueError(
                "planned configurations differ from recorded native outcomes"
            )
        results.append(
            {
                "scenario": name,
                "base": base,
                "head": head,
                "mode": plan["mode"],
                "selected": len(plan["selected"]),
                "build_only": len(plan["build_only"]),
                "fallback": plan["fallback"],
                "digest": plan["digest"],
                "repeat_identical": True,
                "identities_match_recorded_native_outcomes": True,
                "configurations_match_recorded_native_outcomes": True,
            }
        )
    spoiled = output / "tampered-bundle"
    shutil.copytree(bundle, spoiled)
    with (spoiled / "query.xml").open("ab") as stream:
        stream.write(b" ")
    result = output / "tampered.json"
    cli(
        "plan",
        "--repo",
        args.repo,
        "--base",
        base,
        "--head",
        head,
        "--profile",
        profile_path,
        "--bundle",
        spoiled,
        "--expected-digest",
        digest,
        "--execution-mode",
        "selective",
        "--output",
        result,
    )
    bad = document(result)
    if (
        bad["patterns"] != ["..."]
        or bad["production_omission_authorized"]
        or bad["fallback"] != ["MISSING_INVALID_OR_INCOMPATIBLE_NATIVE_EVIDENCE"]
    ):
        raise ValueError("tampered evidence did not retain full execution")
    summary = {
        "schema_version": "smartci.bazel-bundle-verification.v1",
        "capture_anchor": ANCHOR,
        "native_reference_revision": NATIVE_HEAD,
        "capture_source_inputs_match": True,
        "capture_workflow_only_differences": differences,
        "bundle_digest": digest,
        "scenarios": results,
        "tampered_bundle_requires_full": True,
        "new_native_test_execution": False,
        "performance_measurement": False,
        "model_calls": 0,
    }
    (output / "verification.json").write_bytes(canonical(summary))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
