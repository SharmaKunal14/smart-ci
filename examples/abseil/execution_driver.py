"""Execute the reviewed Abseil profile; inventories come from fresh native events."""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from diagnostics import run_profile
from evaluate import git_output, selected_profile, verify_checkout
from native_cache import cache_arguments, validate_profile_options

from smartci.bazel.bundle import canonical, parse_profile, read_bounded
from smartci.bazel.collection import CaptureCommand
from smartci.bazel.execution import ExecutionConfig

# Reviewed full native options plus only --target_pattern_file=/evidence/targets.txt.
SUBSET_OPTIONS = "924ebed1d0ffc56fc3a7fe4c4d96ba1881aa27b9ba95566916b282cd771b5ef2"
CACHED_SUBSET_OPTIONS = (
    "1295f68dc45a7afa3cc618706f2b9f73d27b91146254716a3dbd0e8459cab0ff"
)


def configure(
    profile_path: Path, output: Path, native_cache: Path | None = None
) -> None:
    profile = parse_profile(read_bounded(profile_path, 16384))
    validate_profile_options(profile.options_digest, native_cache)
    config = ExecutionConfig(
        schema_version="1",
        profile=profile,
        subset_options_digest=CACHED_SUBSET_OPTIONS if native_cache else SUBSET_OPTIONS,
        **{
            stage: CaptureCommand(
                argv=[
                    sys.executable,
                    str(Path(__file__).resolve()),
                    stage,
                    "--repo",
                    "{repo}",
                    "--capture",
                    "{capture}",
                ]
                + (["--native-cache", str(native_cache)] if native_cache else []),
                timeout_seconds=1380,
            )
            for stage in ("full", "subset")
        },
    )
    output.write_bytes(canonical(config.model_dump()))


def execute(
    stage: str, root: Path, output: Path, native_cache: Path | None = None
) -> int:
    if output.is_relative_to(root) or not re.fullmatch(
        r"[/._a-zA-Z0-9-]+", str(output)
    ):
        raise ValueError("external simple capture path required")
    revision = git_output(root, ["rev-parse", "HEAD"], 128).decode().strip()
    raw = verify_checkout(root, revision)
    profile = output / "native-profile.sh"
    profile.write_bytes(selected_profile(raw, stage == "subset"))
    name = "smartci-native-pr-" + uuid.uuid4().hex
    cache_mount, cache_option = cache_arguments(native_cache, root, output)
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if key in os.environ
    }
    environment.update(
        ABSEIL_ROOT=str(root),
        STD="c++17",
        COMPILATION_MODE="fastbuild",
        EXCEPTIONS_MODE="-fno-exceptions",
        DOCKER_EXTRA_ARGS=f"--name {name} --mount type=bind,source={output},target=/evidence"
        + cache_mount,
        BAZEL_EXTRA_ARGS="--build_event_json_file=/evidence/native.bep.json"
        + cache_option,
    )
    try:
        code, seconds, error = run_profile(profile, output, environment, timeout=1200)
    finally:
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
            capture_output=True,
            timeout=20,
            check=True,
        )
        if remaining.stdout.strip():
            subprocess.run(
                ["docker", "rm", "--force", name],
                check=True,
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    (output / "command.json").write_bytes(
        canonical({"exit_code": code, "command_seconds": seconds, "error": error})
    )
    return code if 0 < code <= 255 else 1 if code < 0 or error else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["configure", "full", "subset"])
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
            json.dumps({"status": "error", "code": "NATIVE_EXECUTION_DRIVER_FAILED"}),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
