"""Credential-filtered, bounded POSIX native execution shared with Action fallback."""

import os
import signal
import subprocess
import time
from pathlib import Path


def run_argv(arguments: list[str], repo: Path, timeout_seconds: int) -> int:
    if os.name != "posix":
        raise ValueError("POSIX process-group execution required")
    if (
        not 1 <= len(arguments) <= 64
        or not Path(arguments[0]).is_absolute()
        or any(
            not value or len(value) > 4096 or any(c in value for c in "\0\r\n")
            for value in arguments
        )
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= 1800
    ):
        raise ValueError("invalid bounded native command")
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
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    return 124
                try:
                    return process.wait(timeout=min(15, remaining))
                except subprocess.TimeoutExpired:
                    print("Native command is still running...", flush=True)
        finally:
            # Kill the group even if its leader exited while a child was alive.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
