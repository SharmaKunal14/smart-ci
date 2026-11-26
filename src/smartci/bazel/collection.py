"""Collect or reuse native maps using commands from trusted enrollment policy.

Commands execute repository-owned build logic. Run this only on an isolated,
credential-free runner; a capture is not a sandbox or publisher authentication.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from .bundle import (
    LIMITS,
    MAX_MANIFEST_BYTES,
    Bundle,
    Profile,
    StrictModel,
    canonical,
    full_native_inventory,
    load,
    pack,
    read_bounded,
    sha256,
    validate_artifacts,
)
from .events import unique_object
from .graph import QueryError
from .planning import changed_paths, control_path, parse_tree, reusable_change

Argument = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class CaptureCommand(StrictModel):
    argv: list[Argument] = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(ge=1, le=1800)

    @field_validator("argv")
    @classmethod
    def safe_arguments(cls, value: list[str]) -> list[str]:
        if not Path(value[0]).is_absolute() or any(
            "\0" in arg or "\n" in arg or "\r" in arg for arg in value
        ):
            raise ValueError("absolute executable and single-line arguments required")
        if "{repo}" in value[0] or "{capture}" in value[0]:
            raise ValueError("executable cannot be supplied by the repository")
        return value


class CaptureConfig(StrictModel):
    schema_version: Literal["1"]
    profile: Profile
    native: CaptureCommand
    query: CaptureCommand


def read_config(path: Path) -> CaptureConfig:
    raw = read_bounded(path, MAX_MANIFEST_BYTES)
    return CaptureConfig.model_validate(
        json.loads(raw, object_pairs_hook=unique_object)
    )


def run_command(command: CaptureCommand, repo: Path, capture: Path) -> int:
    """No shell, inherited credentials, retries or unbounded captured output."""
    if os.name != "posix":
        raise QueryError("isolated process-group execution requires POSIX")
    arguments = [
        value.replace("{repo}", str(repo)).replace("{capture}", str(capture))
        for value in command.argv
    ]
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if key in os.environ
    }
    # This environment filter is not filesystem isolation. Use a disposable
    # runner with no persisted credentials or private user configuration.
    started = time.monotonic()
    with subprocess.Popen(
        arguments,
        cwd=repo,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        try:
            while True:
                remaining = command.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    return 124
                try:
                    return process.wait(timeout=min(15, remaining))
                except subprocess.TimeoutExpired:
                    print("Native evidence collection is still running...", flush=True)
        finally:
            # Kill the group even if its leader exited while a child was alive.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def reusable_bundle(
    directory: Path, digest: str, config: CaptureConfig, repo: Path, tree: bytes
) -> tuple[Bundle, dict[str, bytes]]:
    # Import lazily because the CLI also exposes collection.
    from .commands import revision_tree

    bundle = load(directory, digest, config.profile)
    if bundle.manifest.capture_config_digest != sha256(canonical(config.model_dump())):
        raise QueryError("collection commands changed or are not bound to this map")
    if parse_tree(revision_tree(repo, bundle.manifest.anchor_commit)) != bundle.anchor:
        raise QueryError("cached anchor tree mismatch")
    current = parse_tree(tree)
    if any(
        not control_path(path)
        and not reusable_change(path, bundle.anchor, current, bundle.graph)
        for path in changed_paths(bundle.anchor, current)
    ):
        raise QueryError("cached graph inputs changed")
    # Bind a second read to the authenticated manifest before copying; never
    # promote bytes changed between validation and publication.
    artifacts = {
        name: read_bounded(directory / name, limit) for name, limit in LIMITS.items()
    }
    validate_artifacts(bundle.manifest, artifacts)
    return bundle, artifacts


def collect(
    repo: Path,
    revision: str,
    config: CaptureConfig,
    output: Path,
    *,
    reuse: Path | None = None,
    expected_digest: str | None = None,
) -> dict[str, object]:
    from .commands import verify_checkout

    tree = verify_checkout(repo, revision)
    if output.is_relative_to(repo) or (
        reuse is not None
        and (output.is_relative_to(reuse) or reuse.is_relative_to(output))
    ):
        raise QueryError("collection output overlaps inputs")
    output.mkdir(mode=0o700, exist_ok=False)
    report: dict[str, object] = {
        "schema_version": "smartci.bazel-collection.v1",
        "revision": revision,
        "config_digest": sha256(canonical(config.model_dump())),
        "status": "failed",
        "cache": "not_supplied" if reuse is None else "rejected",
        "native_exit": None,
        "query_exit": None,
        "manifest_digest": None,
        "model_calls": 0,
    }
    stage = "CACHE_VALIDATION"
    try:
        previous = None
        if reuse is not None and expected_digest is not None:
            try:
                previous = reusable_bundle(reuse, expected_digest, config, repo, tree)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                RecursionError,
            ):
                print(
                    "Cached evidence is unusable; rebuilding the native map.",
                    flush=True,
                )
        if previous is not None:
            stage = "CACHE_PUBLICATION"
            cached, artifacts = previous
            verify_checkout(repo, revision)
            bundle = pack(
                output / "bundle",
                config.profile,
                cached.manifest.anchor_commit,
                artifacts,
                capture_config_digest=cached.manifest.capture_config_digest,
            )
            report["cache"] = "reused"
        else:
            capture = output / "capture"
            capture.mkdir(mode=0o700)
            stage = "NATIVE_EXECUTION"
            print(
                "Running the complete native command to establish map evidence...",
                flush=True,
            )
            report["native_exit"] = run_command(config.native, repo, capture)
            if report["native_exit"] != 0:
                raise QueryError("native command failed")
            stage = "NATIVE_VALIDATION"
            native = read_bounded(
                capture / "native.bep.json", LIMITS["native.bep.json"]
            )
            full_native_inventory(native, config.profile)
            verify_checkout(repo, revision)
            stage = "QUERY_EXECUTION"
            print(
                "Collecting declared dependencies in the native toolchain...",
                flush=True,
            )
            report["query_exit"] = run_command(config.query, repo, capture)
            if report["query_exit"] != 0:
                raise QueryError("query command failed")
            stage = "QUERY_VALIDATION"
            if (
                read_bounded(capture / "bazel-version.txt", 256).strip()
                != ("bazel " + config.profile.bazel_version).encode()
            ):
                raise QueryError("query toolchain mismatch")
            if (
                read_bounded(capture / "native.bep.json", LIMITS["native.bep.json"])
                != native
            ):
                raise QueryError("query command changed native evidence")
            if verify_checkout(repo, revision) != tree:
                raise QueryError("source revision changed during collection")
            artifacts = {
                "anchor.tree": tree,
                "native.bep.json": native,
                "query.xml": read_bounded(capture / "query.xml", LIMITS["query.xml"]),
                "roots.txt": read_bounded(capture / "roots.txt", LIMITS["roots.txt"]),
            }
            stage = "BUNDLE_PUBLICATION"
            bundle = pack(
                output / "bundle",
                config.profile,
                revision,
                artifacts,
                capture_config_digest=sha256(canonical(config.model_dump())),
            )
        report.update(
            status="ready",
            manifest_digest=bundle.manifest_digest,
            map_revision=bundle.manifest.anchor_commit,
            native_test_targets=len(bundle.native.tests),
            native_build_only_targets=len(bundle.native.build_only),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        subprocess.SubprocessError,
    ):
        report["error"] = stage + "_FAILED"
    # A failed collection never supplies a usable receipt. A caller must require
    # status=ready, exit=0 and trusted run provenance before consuming a bundle.
    (output / "collection.json").write_bytes(canonical(report))
    return report
