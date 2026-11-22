"""Diagnose one native failure. This is not a selector or performance baseline."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

from baseline import summarize_events

PROFILE_SHA256 = "03239a4a9294eecfa5270d397cb0250824f8930e6dcc42c4fe37955ae0c2ade1"
TARGET = "//absl/functional:function_ref_test"
UPSTREAM = "82530019412ff77ff99d39ba0ad12e5ea6b89ea4"
PROC_FILES = (
    "loadavg",
    "meminfo",
    "vmstat",
    "stat",
    "pressure/cpu",
    "pressure/memory",
    "pressure/io",
    "sys/kernel/core_pattern",
    "sys/kernel/core_pipe_limit",
)


def targeted_profile(raw: bytes, scope: str = "target") -> bytes:
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError("upstream profile changed; review required")
    original = b"/usr/local/bin/bazel test ..."
    if raw.count(original) != 1:
        raise ValueError("ambiguous native target command")
    if scope == "full":
        return raw
    if scope != "target":
        raise ValueError("unsupported native scope")
    return raw.replace(original, b"/usr/local/bin/bazel test " + TARGET.encode())


def resource_snapshot(proc_root: Path = Path("/proc")) -> dict[str, object]:
    values: dict[str, object] = {}
    for name in PROC_FILES:
        try:
            with (proc_root / name).open("rb") as stream:
                raw = stream.read(16_385)
            if len(raw) > 16_384:
                raise ValueError("proc field exceeds bound")
            values[name] = raw.decode("ascii")
        except (OSError, ValueError):
            values[name] = None
    # Process names only: do not collect argv, environment, stacks or core dumps.
    helpers = {"apport": 0, "systemd-coredum": 0, "addr2line": 0, "llvm-symbolizer": 0}
    for entry in proc_root.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            with (entry / "comm").open() as stream:
                name = stream.read(64).strip()
            if name in helpers:
                helpers[name] += 1
        except OSError:
            continue  # A process may exit between directory listing and open.
    values["helper_process_counts"] = helpers
    return values


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    except ProcessLookupError:
        process.wait(timeout=10)


def run_profile(
    script: Path, output: Path, environment: dict[str, str], timeout: float = 600
) -> tuple[int, float, str | None]:
    started = time.monotonic()
    error = None
    with (
        (output / "native.log").open("wb") as log,
        (output / "resources.jsonl").open("w") as telemetry,
        subprocess.Popen(
            ["bash", str(script)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process,
    ):
        try:
            while True:
                elapsed = time.monotonic() - started
                telemetry.write(
                    json.dumps({"elapsed_seconds": elapsed, **resource_snapshot()})
                    + "\n"
                )
                telemetry.flush()
                if elapsed >= timeout:
                    error = "DIAGNOSTIC_TIMEOUT"
                    stop(process)
                    return 124, elapsed, error
                if log.tell() > 32 * 1024 * 1024:
                    error = "DIAGNOSTIC_LOG_LIMIT"
                    stop(process)
                    return 125, elapsed, error
                try:
                    code = process.wait(timeout=5)
                    return code, time.monotonic() - started, None
                except subprocess.TimeoutExpired:
                    print(
                        f"Native diagnostic still running ({int(elapsed)}s)...",
                        flush=True,
                    )
        finally:
            stop(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=["target", "full"], default="target")
    args = parser.parse_args()
    root, output = Path.cwd().resolve(), args.output.resolve()
    if output.is_relative_to(root) or any(
        c not in "/._-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for c in str(output)
    ):
        parser.error("external new output directory with simple path required")
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            UPSTREAM,
            "--",
            "absl",
            "ci",
            "MODULE.bazel",
            "MODULE.bazel.lock",
            "BUILD.bazel",
            ".bazelrc",
        ],
        check=True,
        timeout=10,
        stdout=subprocess.DEVNULL,
    )
    script = targeted_profile(
        (root / "ci/linux_gcc-latest_libstdcxx_bazel.sh").read_bytes(), args.scope
    )
    output.mkdir(parents=True, exist_ok=False)
    profile = output / "targeted-native.sh"
    profile.write_bytes(script)
    name = "smartci-diagnostic-" + uuid.uuid4().hex
    environment = dict(os.environ)
    for key in ("KOKORO_KEYSTORE_DIR", "KOKORO_GFILE_DIR", "ALTERNATE_OPTIONS"):
        environment.pop(key, None)
    environment.update(
        {
            "ABSEIL_ROOT": str(root),
            "STD": "c++17",
            "COMPILATION_MODE": "fastbuild",
            "EXCEPTIONS_MODE": "-fno-exceptions",
            "DOCKER_EXTRA_ARGS": f"--name {name} --mount type=bind,source={output},target=/evidence",
            "BAZEL_EXTRA_ARGS": "--build_event_json_file=/evidence/native.bep.json"
            + (" --test_output=all" if args.scope == "target" else ""),
        }
    )
    print(
        f"Running native {args.scope} scope; no TIA selection.",
        flush=True,
    )
    started = time.monotonic()
    try:
        code, elapsed, error = run_profile(
            profile, output, environment, timeout=1200 if args.scope == "full" else 600
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        code, elapsed, error = 125, time.monotonic() - started, "DIAGNOSTIC_FAILED"
    cleanup_error = False
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
            cleanup_error = True
    events = None
    try:
        events = summarize_events(output / "native.bep.json")
        if events["exit_code"] != code or (
            args.scope == "target" and set(events["test_targets"]) != {TARGET}
        ):
            raise ValueError("native target or exit mismatch")
        if args.scope == "full" and any(
            status != "PASSED" for status in events["test_targets"].values()
        ):
            error = "FULL_BASELINE_HAS_NONPASS_TARGETS"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        error = error or "DIAGNOSTIC_EVIDENCE_INVALID"
    report = {
        "schema_version": "smartci.native-diagnostic.v1",
        "scope": "one_complete_native_target; not_TIA_or_full_baseline"
        if args.scope == "target"
        else "complete_native_profile; not_TIA",
        "upstream": UPSTREAM,
        "profile_sha256": PROFILE_SHA256,
        "derived_profile_sha256": hashlib.sha256(script).hexdigest(),
        "target": TARGET if args.scope == "target" else "...",
        "command_seconds": elapsed,
        "exit_code": code,
        "evidence_error": error,
        "cleanup_error": cleanup_error,
        "bazel": events,
        "changes": [
            "explicit diagnostic target",
            "test output verbosity",
            "read-only resource sampling",
        ]
        if args.scope == "target"
        else ["read-only resource sampling"],
        "omission_authorized": False,
        "speedup_demonstrated": False,
        "model_calls": 0,
    }
    (output / "diagnostic.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    return code if code > 0 else 1 if code < 0 or error or cleanup_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
