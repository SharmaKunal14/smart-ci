"""Reviewed Abseil native profile adapter for the generic map collector.

No saved graph, run ID or benchmark inventory is read here. The full native
command and query run afresh when the collector requires evidence rebuilding.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from diagnostics import run_profile, targeted_profile
from evaluate import git_output, verify_checkout
from native_cache import cache_arguments, validate_profile_options
from query import prepare_archive, query_profile

from smartci.bazel.bundle import LIMITS, canonical, parse_profile, read_bounded
from smartci.bazel.collection import CaptureCommand, CaptureConfig


def configure(
    profile_path: Path, output: Path, native_cache: Path | None = None
) -> None:
    profile = parse_profile(profile_path.read_bytes())
    validate_profile_options(profile.options_digest, native_cache)
    driver = str(Path(__file__).resolve())
    config = CaptureConfig(
        schema_version="1",
        profile=profile,
        **{
            stage: CaptureCommand(
                argv=[
                    sys.executable,
                    driver,
                    stage,
                    "--repo",
                    "{repo}",
                    "--capture",
                    "{capture}",
                ]
                + (["--native-cache", str(native_cache)] if native_cache else []),
                timeout_seconds=timeout,
            )
            for stage, timeout in [("native", 1380), ("query", 720)]
        },
    )
    output.write_bytes(canonical(config.model_dump()))


def execute(
    stage: str, root: Path, capture: Path, native_cache: Path | None = None
) -> int:
    if not re.fullmatch(r"[/._a-zA-Z0-9-]+", str(capture)) or capture.is_relative_to(
        root
    ):
        raise ValueError("external simple capture path required")
    revision = git_output(root, ["rev-parse", "HEAD"], 128).decode().strip()
    raw = verify_checkout(root, revision)
    output = capture / stage
    output.mkdir(mode=0o700, exist_ok=False)
    profile = output / "native-profile.sh"
    profile.write_bytes(
        targeted_profile(raw, "full") if stage == "native" else query_profile(raw)
    )
    name = "smartci-collection-" + uuid.uuid4().hex
    cache_mount, cache_option = cache_arguments(native_cache, root, capture)
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
            "DOCKER_EXTRA_ARGS": f"--name {name} --mount type=bind,source={output},target=/evidence"
            + cache_mount,
        }
    )
    if stage == "native":
        environment["BAZEL_EXTRA_ARGS"] = (
            "--build_event_json_file=/evidence/native.bep.json" + cache_option
        )
    else:
        archive = prepare_archive(output, environment)
        (output / "archive.json").write_bytes(canonical(archive))
    try:
        code, elapsed, error = run_profile(
            profile, output, environment, timeout=1200 if stage == "native" else 600
        )
    finally:
        # The native script uses --rm. A nonzero cleanup result after normal exit
        # is expected; a still-running named container must not be left behind.
        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
            capture_output=True,
            timeout=20,
            check=True,
        )
        if result.stdout.strip():
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=True,
            )
    (output / "command.json").write_bytes(
        canonical({"exit_code": code, "error": error, "command_seconds": elapsed})
    )
    if code != 0 or error:
        return 1
    members = (
        ["native.bep.json"]
        if stage == "native"
        else ["query.xml", "roots.txt", "bazel-version.txt", "buildfiles.txt"]
    )
    for member in members:
        limit = LIMITS.get(member, 4 * 1024 * 1024)
        with (capture / member).open("xb") as stream:
            stream.write(read_bounded(output / member, limit))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["configure", "native", "query"])
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--native-cache", type=Path)
    args = parser.parse_args()
    if args.stage == "configure":
        if args.profile is None or args.output is None:
            parser.error("profile and output required")
        configure(args.profile, args.output, args.native_cache)
        return 0
    if args.repo is None or args.capture is None:
        parser.error("repo and capture required")
    try:
        return execute(
            args.stage, args.repo.resolve(), args.capture.resolve(), args.native_cache
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            json.dumps({"status": "error", "code": "NATIVE_CAPTURE_DRIVER_FAILED"}),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
