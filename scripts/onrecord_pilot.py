"""Reproduce the OnRecord pilot in a disposable checkout without modifying its source."""

import argparse
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from smartci.discovery.commands import write_json
from smartci.typescript.commands import command, planning
from smartci.typescript.models import TypeScriptConfig, TypeScriptSnapshot
from smartci.typescript.native import NativeVitest

ROOT = Path(__file__).resolve().parents[1]
PIN = "cfcb957baee9a6e90b0f156f4458b33994117287"


def git(root, *args):
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
    )


def commit(root, message):
    git(root, "add", "src/domain/incident.ts", "package-lock.json")
    git(
        root,
        "-c",
        "user.name=Smart CI Pilot",
        "-c",
        "user.email=pilot@example.invalid",
        "commit",
        "-qm",
        message,
    )


def verify(source, offline):
    parent = ROOT / "demo-output/onrecord"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="verification-", dir=parent))
    root = output / "repository"
    print(f"Creating disposable checkout; artifacts: {output}", flush=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            "--",
            str(source),
            str(root),
        ],
        check=True,
        timeout=120,
    )
    git(root, "checkout", "--detach", PIN)
    dependencies = source / "node_modules"
    if not (dependencies / "vitest/vitest.mjs").is_file():
        raise ValueError("source needs installed OnRecord dependencies")
    # Copy dependencies; never share a mutable Vite cache with the user's checkout.
    if platform.system() == "Darwin":
        subprocess.run(
            ["cp", "-cR", str(dependencies), str(root / "node_modules")],
            check=True,
            timeout=180,
        )
    else:
        shutil.copytree(dependencies, root / "node_modules", symlinks=True)
    config_path = ROOT / "examples/onrecord/typescript.json"
    config = TypeScriptConfig.model_validate_json(config_path.read_bytes())
    runner = NativeVitest(root, offline=offline)
    args = argparse.Namespace(
        repo=root,
        config=config_path,
        output=output / "initial",
        node=None,
        offline=offline,
        ts_action="scan",
        run_full=True,
        shadow=False,
        base=PIN,
    )
    if command(args) != 0:
        raise ValueError("native baseline did not pass")
    source_file = root / "src/domain/incident.ts"
    source_file.write_text(
        source_file.read_text() + "\n// Smart CI harmless domain change.\n"
    )
    commit(root, "Verify a harmless domain change")
    args.ts_action, args.output = "run", output / "subset"
    if command(args) != 0:
        raise ValueError("subset run did not pass")
    proposal = json.loads((args.output / "selection.json").read_text())
    if proposal["execution"] != "subset" or not proposal["omitted"]:
        raise ValueError("pilot did not reduce the test files")
    repeated = output / "rebuilt"
    repeated.mkdir()
    print("Rebuilding both maps again without reading prior output", flush=True)
    repeat, _ = planning(runner, config, PIN, False, repeated)
    write_json(repeated / "selection.json", repeat.model_dump())
    if repeat.model_dump() != proposal:
        raise ValueError("nondeterministic plan")
    content = source_file.read_text()
    if content.count("version: this.snapshot.version + 1,") != 1:
        raise ValueError("pinned defect location changed")
    source_file.write_text(
        content.replace(
            "version: this.snapshot.version + 1,", "version: this.snapshot.version + 2,"
        )
    )
    commit(root, "Inject a lifecycle version defect")
    args.output = output / "defect"
    if command(args) != 1:
        raise ValueError("seeded defect was not caught")
    subset = json.loads((args.output / "run.json").read_text())
    snapshot = TypeScriptSnapshot.model_validate_json(
        (args.output / "head-map.json").read_bytes()
    )
    print(
        "Running independent full-suite ground truth for the seeded defect", flush=True
    )
    full = runner.run(snapshot.files, subset=False)
    write_json(output / "defect-full.json", full.model_dump())
    if (
        not full.failed_cases
        or full.failed_cases != subset["attempts"][-1]["failed_cases"]
    ):
        raise ValueError("subset missed or added a failing case")
    source_file.write_text(content)
    lock = root / "package-lock.json"
    lock.write_bytes(lock.read_bytes() + b"\n")
    commit(root, "Restore code and verify manifest-change fallback")
    args.output = output / "lockfile"
    if command(args) != 0:
        raise ValueError("fallback run did not pass")
    fallback = json.loads((args.output / "run.json").read_text())
    if fallback["execution"] != "full" or not fallback["fallback"]:
        raise ValueError("manifest change did not trigger full fallback")
    summary = {
        "source_commit": PIN,
        "deterministic_rebuild": True,
        "subset_failed_cases": subset["attempts"][-1]["failed_cases"],
        "full_failed_cases": full.failed_cases,
        "all_scenarios_verified": True,
    }
    write_json(output / "verification.json", summary)
    print(f"All OnRecord scenarios verified. Artifacts: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="existing local OnRecord checkout with installed dependencies",
    )
    parser.add_argument(
        "--offline", action="store_true", help="macOS outbound network isolation"
    )
    args = parser.parse_args()
    verify(args.source.resolve(strict=True), args.offline)


if __name__ == "__main__":
    main()
