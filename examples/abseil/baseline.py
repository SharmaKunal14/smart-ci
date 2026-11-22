"""Measure an unchanged upstream Bazel profile; never mask native failures."""

import argparse
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path


def summarize_events(path: Path) -> dict[str, object]:
    """Read native target results, not an invented count of internal test cases."""
    summaries: dict[str, str] = {}
    finished: int | None = None
    last_message = False
    total = 0
    with path.open("rb") as stream:
        while line := stream.readline(8 * 1024 * 1024 + 1):
            total += len(line)
            if total > 64 * 1024 * 1024 or len(line) > 8 * 1024 * 1024:
                raise ValueError("build events exceed limit")
            event = json.loads(line)
            if not isinstance(event, dict):
                raise TypeError("invalid build event")
            if "testSummary" in event:
                label = event["id"]["testSummary"]["label"]
                status = event["testSummary"]["overallStatus"]
                if (
                    not isinstance(label, str)
                    or not label.startswith("//")
                    or label in summaries
                    or status
                    not in {
                        "PASSED",
                        "FLAKY",
                        "TIMEOUT",
                        "FAILED",
                        "INCOMPLETE",
                        "REMOTE_FAILURE",
                        "FAILED_TO_BUILD",
                        "TOOL_HALTED_BEFORE_TESTING",
                    }
                ):
                    raise ValueError("invalid or duplicate test summary")
                summaries[label] = status
            if "finished" in event:
                if finished is not None:
                    raise ValueError("duplicate build completion")
                exit_code = event["finished"]["exitCode"]
                finished = exit_code.get("code")
                if finished is None and exit_code.get("name") == "SUCCESS":
                    finished = 0
                if type(finished) is not int:
                    raise ValueError("invalid build exit code")
            last_message = last_message or event.get("lastMessage") is True
    if finished is None or not last_message or not summaries:
        raise ValueError("incomplete native build evidence")
    return {
        "complete_stream": True,
        "exit_code": finished,
        "test_target_count": len(summaries),
        "test_targets": dict(sorted(summaries.items())),
    }


def run_native(command: list[str], environment: dict[str, str], timeout: float) -> int:
    with subprocess.Popen(command, env=environment, start_new_session=True) as process:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            return 124


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output.resolve()
    # This path is inserted into the upstream script's documented Docker-argument
    # hook. Reject shell tokenization characters rather than interpreting them.
    if output.is_relative_to(root) or any(
        c not in "/._-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for c in str(output)
    ):
        parser.error("new external output directory with simple path required")
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ)
    container_name = "smartci-baseline-" + uuid.uuid4().hex
    for key in ("KOKORO_KEYSTORE_DIR", "KOKORO_GFILE_DIR", "ALTERNATE_OPTIONS"):
        environment.pop(key, None)
    environment.update(
        {
            "STD": "c++17",
            "COMPILATION_MODE": "fastbuild",
            "EXCEPTIONS_MODE": "-fno-exceptions",
            "DOCKER_EXTRA_ARGS": f"--name {container_name} --mount type=bind,source={output},target=/evidence",
            "BAZEL_EXTRA_ARGS": "--build_event_json_file=/evidence/native.bep.json",
        }
    )
    started = time.monotonic()
    print("Running upstream GCC/Bazel C++17 fastbuild profile...", flush=True)
    error = None
    try:
        code = run_native(
            ["bash", "ci/linux_gcc-latest_libstdcxx_bazel.sh"],
            environment,
            1200,
        )
    except OSError:
        code = 125
        error = "NATIVE_START_FAILED"
    if code == 124:
        error = "NATIVE_TIMEOUT"
        # Stop only the unique container created by this invocation. Killing the
        # client process alone does not stop a Docker daemon's running container.
        try:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                check=False,
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            error = "NATIVE_TIMEOUT_CONTAINER_CLEANUP_FAILED"
    elapsed = time.monotonic() - started
    events = None
    try:
        events = summarize_events(output / "native.bep.json")
        if events["exit_code"] != code:
            error = "NATIVE_EVIDENCE_EXIT_MISMATCH"
    except (OSError, ValueError, KeyError, TypeError):
        error = error or "NATIVE_EVIDENCE_MISSING_OR_INVALID"
    report = {
        "schema_version": "1",
        "mode": "native",
        "profile": "upstream GCC C++17 fastbuild without optional private remote cache",
        "command_seconds": elapsed,
        "exit_code": code,
        "evidence_error": error,
        "bazel": events,
    }
    (output / "execution.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    return code if code > 0 else 1 if code < 0 or error else 0


if __name__ == "__main__":
    raise SystemExit(main())
