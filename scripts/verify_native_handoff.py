"""Hosted handoff check for a fresh native publisher; never runs native tests.

The pinned source cases are real earlier PRs, replayed against the newly collected
map. Their old timings are not measurements of this workflow or this map.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from smartci.bazel.bundle import canonical, parse_profile, read_bounded, sha256
from smartci.bazel.collection import (
    CaptureCommand,
    CaptureConfig,
    read_config,
    reusable_bundle,
)
from smartci.bazel.commands import verify_checkout
from smartci.bazel.transport import Publisher

TOOL = Path(__file__).resolve().parents[1]
PRODUCER_REVISION = "622fd1c2829655d595ffeca8656382ff305a5ddb"
PRODUCER_TOOL = "595547f45437b438ba17cca45b2c6f2c4af61ffb"
PRODUCER_ROOT = "/home/runner/work/abseil-cpp/abseil-cpp/tool"
CASES = (
    (
        10,
        "6caf49f391bac80d83d81ad925cd29ae75872f3e",
        "2745f8c71cfe5e04081b68e3cab6bea4fab069e6",
        "subset",
    ),
    (
        11,
        "2745f8c71cfe5e04081b68e3cab6bea4fab069e6",
        "2d5a7985bfe983dc080a5dd62db3fdf203f526ff",
        "full",
    ),
)


def document(path: Path) -> dict:
    return json.loads(read_bounded(path, 1024 * 1024))


def prepare(output: Path) -> None:
    output.mkdir(mode=0o700, exist_ok=False)
    config_path = output / "capture-config.json"
    # Bind the reviewed Linux publisher's command identity, independently of the
    # consumer's interpreter symlink/workspace. These commands are never executed.
    config_value = CaptureConfig(
        schema_version="1",
        profile=parse_profile(
            read_bounded(TOOL / "examples/abseil/capture-profile.json", 16384)
        ),
        **{
            stage: CaptureCommand(
                argv=[
                    PRODUCER_ROOT + "/.venv/bin/python3",
                    PRODUCER_ROOT + "/examples/abseil/collection_driver.py",
                    stage,
                    "--repo",
                    "{repo}",
                    "--capture",
                    "{capture}",
                ],
                timeout_seconds=timeout,
            )
            for stage, timeout in (("native", 1380), ("query", 720))
        },
    )
    config_path.write_bytes(canonical(config_value.model_dump()))
    (output / "profile.json").write_bytes(canonical(config_value.profile.model_dump()))
    workflow = (
        (TOOL / "examples/abseil/collection-workflow.yml")
        .read_text()
        .replace("REVIEWED_TOOL_COMMIT", PRODUCER_TOOL)
    )
    publisher = Publisher(
        repository="SharmaKunal14/abseil-cpp",
        branch="codex/native-collection-onboarding",
        workflow=".github/workflows/smartci-native-query.yml",
        workflow_digest=sha256(workflow.encode()),
        artifact_prefix="native-enrollment",
    )
    (output / "publisher.json").write_bytes(canonical(publisher.model_dump()))


def plan(
    repo: Path, output: Path, bundle: Path, digest: str, base: str, head: str, name: str
) -> dict:
    subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            "checkout",
            "--quiet",
            "--detach",
            head,
        ],
        check=True,
        timeout=30,
    )
    for attempt in (1, 2):
        subprocess.run(
            [
                "smartci",
                "bazel",
                "plan",
                "--repo",
                str(repo),
                "--base",
                base,
                "--head",
                head,
                "--profile",
                str(output / "profile.json"),
                "--bundle",
                str(bundle),
                "--expected-digest",
                digest,
                "--output",
                str(output / f"{name}-{attempt}.json"),
            ],
            check=True,
            timeout=60,
        )
    first, second = (output / f"{name}-{n}.json" for n in (1, 2))
    if first.read_bytes() != second.read_bytes():
        raise ValueError("repeated native plan differs")
    return document(first)


def verify(repo: Path, output: Path) -> None:
    first = document(output / "fetched/fetch.json")
    second = document(output / "repeated/fetch.json")
    if first != second or first["revision"] != PRODUCER_REVISION:
        raise ValueError("retrieval is not stable or revision-bound")
    bundle_path = output / "fetched/bundle"
    digest = first["manifest_digest"]
    bundle, _ = reusable_bundle(
        bundle_path,
        digest,
        read_config(output / "capture-config.json"),
        repo,
        verify_checkout(repo, PRODUCER_REVISION),
    )
    if len(bundle.native.tests) != 252 or len(bundle.native.build_only) != 324:
        raise ValueError("unexpected native scope")
    cases = []
    for number, base, head, mode in CASES:
        result = plan(repo, output, bundle_path, digest, base, head, f"pr-{number}")
        if (
            result["mode"] != mode
            or result["production_omission_authorized"]
            or not result["requires_independent_full_control"]
            or result["build_only"] != list(bundle.native.build_only)
        ):
            raise ValueError("fresh map changed known PR planning or authority")
        if mode == "subset" and (
            result["fallback"]
            or result["selected"]
            != [
                "//absl/container:linked_hash_map_test",
                "//absl/container:linked_hash_set_test",
            ]
        ):
            raise ValueError("fresh map changed the localized source case")
        if mode == "full" and (result["patterns"] != ["..."] or not result["fallback"]):
            raise ValueError("risk change did not retain independent full execution")
        cases.append(
            {
                "pr": f"https://github.com/SharmaKunal14/abseil-cpp/pull/{number}",
                "base": base,
                "head": head,
                "mode": mode,
                "selected": len(result["selected"]),
                "digest": result["digest"],
                "fallback": result["fallback"],
            }
        )
    damaged = output / "tampered-bundle"
    shutil.copytree(bundle_path, damaged)
    with (damaged / "query.xml").open("ab") as stream:
        stream.write(b"\n")
    _, base, head, _ = CASES[0]
    fallback = plan(repo, output, damaged, digest, base, head, "tampered")
    if fallback["mode"] != "full" or fallback["patterns"] != ["..."]:
        raise ValueError("tampered evidence did not force full execution")
    report = {
        "schema_version": "smartci.native-handoff-verification.v1",
        "status": "passed",
        "publisher": first,
        "native_test_targets": 252,
        "native_build_only_targets": 324,
        "compatible_reuse_validated": True,
        "repeat_plans_identical": True,
        "cases": cases,
        "tampered_map_fallback": fallback["fallback"],
        "native_test_execution": False,
        "performance_measurement": False,
        "model_calls": 0,
    }
    (output / "verification.json").write_bytes(canonical(report))
    print(json.dumps(report, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "verify"])
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.output.resolve())
    else:
        if args.repo is None:
            parser.error("repo required for verification")
        verify(args.repo.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
