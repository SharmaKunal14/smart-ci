"""Bounded real-PR accounting. Selection stays in the released Smart CI CLI."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples/abseil"))
from native_cache import fingerprint

from smartci import action_control as control
from smartci import maven

EXPECTED = {
    "bytes": 182217417,
    "files": 3866,
    "schema_version": "1",
    "tree_digest": "fb4c8772bdf844a2d049d8abca73a25eeeefac9d7d25d5d8a5d1c8c94d8de60d",
}


def stamp():
    return {
        "monotonic_ns": time.monotonic_ns(),
        "utc": datetime.now(UTC).isoformat(),
        "boot": hashlib.sha256(
            Path("/proc/sys/kernel/random/boot_id").read_bytes()
        ).hexdigest(),
    }


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True)


def prepare(temp, workspace, arm):
    record = temp / "comparison" / arm
    write(record / "start.json", stamp())
    repo = workspace / arm
    if repo.exists():
        raise ValueError("fresh arm checkout required")
    head = control.read_object(Path(os.environ["GITHUB_EVENT_PATH"]))["pull_request"][
        "head"
    ]["sha"]
    control.revision(head)
    subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            str(workspace / "source"),
            str(repo),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "--detach", head], check=True, timeout=30
    )
    cache = Path.home() / ".m2/repository"
    if cache.is_symlink():
        raise ValueError("cache symlink")
    if cache.exists():
        cache.rename(
            temp / ("used-maven-cache-" + ("smart" if arm == "full" else "full"))
        )
    wrapper = Path.home() / ".m2/wrapper"
    if wrapper.is_symlink():
        raise ValueError("wrapper cache symlink")
    if wrapper.exists():
        wrapper.rename(temp / ("used-wrapper-before-" + arm))
    # Disposable hosted runner only: discard previous arm's container images and
    # layers, never its reports. Native Docker pulls remain timed native work.
    active = subprocess.check_output(["docker", "ps", "-q"], timeout=20).strip()
    if active:
        raise ValueError("active container prevents independent comparison")
    subprocess.run(
        ["docker", "system", "prune", "--all", "--force"], check=True, timeout=90
    )
    subprocess.run(
        ["docker", "builder", "prune", "--all", "--force"], check=True, timeout=60
    )
    write(
        record / "docker-before.json",
        {
            "images": subprocess.check_output(
                ["docker", "image", "ls", "-q"], text=True, timeout=20
            ).splitlines()
        },
    )


def verify_cache(temp, arm):
    receipt = fingerprint(Path.home() / ".m2/repository")
    write(temp / "comparison" / arm / "cache.json", receipt)
    if receipt != EXPECTED:
        raise ValueError("independent native cache seed differs")
    subprocess.run(["sync"], check=True, timeout=30)
    subprocess.run(
        ["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
        check=True,
        timeout=30,
    )


def full(temp, workspace):
    value = control.context(
        workspace / "full",
        Path(os.environ["GITHUB_EVENT_PATH"]),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_EVENT_NAME"],
    )
    config = maven.configuration(control.base_file(value, ".github/smartci-maven.toml"))
    return maven.run(value, config, temp / "full-result", force_full=True)


def outcomes(repo):
    cases = {}
    files = []
    for path in sorted(repo.glob("*/target/*-reports/TEST-*.xml")):
        files.append(path.relative_to(repo).as_posix())
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            key = "|".join(
                (path.parts[-4], case.get("classname", ""), case.get("name", ""))
            )
            if key in cases:
                raise ValueError("ambiguous case identity")
            cases[key] = (
                "failed"
                if case.find("failure") is not None or case.find("error") is not None
                else "skipped"
                if case.find("skipped") is not None
                else "passed"
            )
    if not cases:
        raise ValueError("native reports absent")
    return cases, files


def settle_containers(record):
    """Wait for native cleanup; never erase an active service to force parity."""
    started = time.monotonic()
    observations = []
    while True:
        active = subprocess.check_output(
            ["docker", "ps", "--format", "{{json .}}"], text=True, timeout=20
        ).splitlines()
        elapsed = time.monotonic() - started
        observations.append(
            {"seconds": elapsed, "containers": [json.loads(row) for row in active]}
        )
        if not active or elapsed >= 45:
            write(
                record / "container-cleanup.json",
                {
                    "seconds": elapsed,
                    "settled": not active,
                    "observations": observations,
                },
            )
            if active:
                raise ValueError(
                    "native containers remain active after bounded cleanup wait"
                )
            return
        print(
            "Waiting for native container cleanup before ending this arm...", flush=True
        )
        time.sleep(min(5, 45 - elapsed))


def finish(temp, workspace, arm):
    record = temp / "comparison" / arm
    cases, files = outcomes(workspace / arm)
    write(record / "cases.json", cases)
    write(record / "reports.json", files)
    settle_containers(record)
    write(
        record / "docker-after.json",
        {
            "images": subprocess.check_output(
                [
                    "docker",
                    "image",
                    "ls",
                    "--digests",
                    "--no-trunc",
                    "--format",
                    "{{json .}}",
                ],
                text=True,
                timeout=20,
            ).splitlines()
        },
    )
    write(record / "end.json", stamp())


def compare(temp):
    root = temp / "comparison"
    records = {}
    for arm in ("full", "smart"):
        start = control.read_object(root / arm / "start.json")
        end = control.read_object(root / arm / "end.json")
        if (
            start["boot"] != end["boot"]
            or control.read_object(root / arm / "cache.json") != EXPECTED
        ):
            raise ValueError("unmatched runner or cache")
        result = temp / (
            "full-result" if arm == "full" else "smartci-native-action/result"
        )
        cases = control.read_object(root / arm / "cases.json")
        records[arm] = {
            "lifecycle_seconds": (end["monotonic_ns"] - start["monotonic_ns"]) / 1e9,
            "execution": control.read_object(result / "execution.json"),
            "selection": control.read_object(result / "selection.json"),
            "cases": len(cases),
            "passed": sum(s == "passed" for s in cases.values()),
            "skipped": sum(s == "skipped" for s in cases.values()),
            "failed": sorted(k for k, v in cases.items() if v == "failed"),
            "boot": start["boot"],
        }
    if records["full"]["boot"] != records["smart"]["boot"]:
        raise ValueError("different hardware")
    full_cases = control.read_object(root / "full/cases.json")
    smart_cases = control.read_object(root / "smart/cases.json")
    mismatches = sorted(k for k, v in smart_cases.items() if full_cases.get(k) != v)
    missed = sorted(set(records["full"]["failed"]) - set(records["smart"]["failed"]))
    report = {
        "arms": records,
        "missed_failures": missed,
        "shared_case_mismatches": mismatches,
        "seconds_saved": records["full"]["lifecycle_seconds"]
        - records["smart"]["lifecycle_seconds"],
    }
    write(root / "result.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)
    expected_regression = os.environ["GITHUB_HEAD_REF"] == "codex/httpclient-regression"
    codes = [r["execution"]["exit_code"] for r in records.values()]
    valid = (
        not missed
        and not mismatches
        and (
            all(c != 0 for c in codes) and bool(records["full"]["failed"])
            if expected_regression
            else codes == [0, 0]
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=["prepare", "cache", "full", "finish", "compare"]
    )
    parser.add_argument("--arm", choices=["full", "smart"])
    args = parser.parse_args()
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise ValueError("hosted disposable runner required")
    if args.operation == "prepare":
        prepare(temp, workspace, args.arm)
    elif args.operation == "cache":
        verify_cache(temp, args.arm)
    elif args.operation == "finish":
        finish(temp, workspace, args.arm)
    elif args.operation == "full":
        raise SystemExit(full(temp, workspace))
    elif args.operation == "compare":
        raise SystemExit(compare(temp))
