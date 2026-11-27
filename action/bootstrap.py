"""Bootstrap a pinned CLI; preserve the base-owned full command if unavailable."""

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# This file and the standard-library control helpers belong to the pinned Action,
# not to the checked-out PR. The actual selector runs from the released wheel.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smartci.action_control import (
    context,
    full_fallback,
    prepare,
    read_object,
    relative,
    write,
)


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in {
            "github.com",
            "objects.githubusercontent.com",
            "release-assets.githubusercontent.com",
        }:
            raise ValueError("unexpected CLI release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def state_root():
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    return root / "smartci-native-action"


def clean_env():
    return {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if key in os.environ
    }


def stage():
    if (
        os.environ.get("RUNNER_OS") != "Linux"
        or os.environ.get("RUNNER_ARCH") != "X64"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise ValueError("first release requires GitHub-hosted Linux x64")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    path = os.environ["SOURCE_PATH"]
    repo = (workspace / relative(path) if path != "." else workspace).resolve(
        strict=True
    )
    if not repo.is_relative_to(workspace):
        raise ValueError("checkout must be inside the workspace")
    value = context(
        repo,
        Path(os.environ["GITHUB_EVENT_PATH"]),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_EVENT_NAME"],
    )
    prepare(value, os.environ["CONFIG_PATH"], state_root(), ROOT)
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"state={state_root()}\n")


def install():
    lock = read_object(ROOT / "action/cli-release.json")
    if set(lock) != {"tag", "wheel", "sha256"}:
        raise ValueError("invalid CLI release pin")
    tag, wheel, digest = lock["tag"], lock["wheel"], lock["sha256"]
    if not (
        isinstance(tag, str)
        and re.fullmatch(r"cli-v[0-9a-z.]+", tag)
        and isinstance(wheel, str)
        and re.fullmatch(r"smartci-[0-9a-z.]+-py3-none-any.whl", wheel)
        and isinstance(digest, str)
        and re.fullmatch(r"[a-f0-9]{64}", digest)
        and wheel == f"smartci-{tag.removeprefix('cli-v')}-py3-none-any.whl"
    ):
        raise ValueError("invalid pinned release identity")
    state = state_root()
    archive = state / wheel
    url = f"https://github.com/SharmaKunal14/smart-ci/releases/download/{tag}/{wheel}"
    with urllib.request.build_opener(ReleaseRedirect()).open(
        url, timeout=30
    ) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("CLI wheel integrity check failed")
    archive.write_bytes(raw)
    environment = {
        **clean_env(),
        "PIP_CONFIG_FILE": os.devnull,
        "PYTHONNOUSERSITE": "1",
    }
    subprocess.run(
        [sys.executable, "-I", "-m", "venv", str(state / "venv")],
        env=environment,
        check=True,
        timeout=60,
    )
    python = state / "venv/bin/python3"
    requirements = state / "requirements.txt"
    requirements.write_text(
        (ROOT / "action/requirements.txt").read_text()
        + f"\n{archive.as_uri()} --hash=sha256:{digest}\n"
    )
    subprocess.run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--require-hashes",
            "--only-binary=:all:",
            "--index-url",
            "https://pypi.org/simple",
            "--retries",
            "2",
            "--timeout",
            "20",
            "-r",
            str(requirements),
        ],
        env=environment,
        check=True,
        timeout=180,
    )
    write(
        state / "installation.json",
        {"python": str(python), "release": tag, "sha256": digest},
    )
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"python={python}\n")


def execute():
    state = state_root()
    if os.environ.get("CLI_READY") != "true":
        value = read_object(state / "context.json")
        return full_fallback(value, read_object(state / "policy.json"), state)
    python = state / "venv/bin/python3"
    force = os.environ.get("FORCE_FULL", "false")
    if force not in {"true", "false"}:
        raise ValueError("force-full must be true or false")
    arguments = [
        str(python),
        "-I",
        "-m",
        "smartci.cli",
        "github-action",
        "execute",
        "--state",
        str(state),
    ]
    if force == "true":
        arguments.append("--force-full")
    # Repo-owned adapters can use /usr/bin/env python3 without installing or
    # locating the CLI themselves. No authentication environment is inherited.
    environment = clean_env()
    environment["PATH"] = str(python.parent) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(arguments, env=environment, timeout=5500, check=False)
    return result.returncode if 0 <= result.returncode <= 255 else 1


def summary():
    state = state_root()
    mode, status, selected, fallback = (
        "unknown",
        "error",
        "unknown",
        "No validated execution report",
    )
    native = state / "native-pr/execution"
    if (native / "execution.json").is_file():
        execution = read_object(native / "execution.json")
        plan = read_object(native / "plan.json")
        if execution.get("mode") in {"full", "subset"}:
            mode = execution["mode"]
        if execution.get("status") in {"passed", "failed"}:
            status = execution["status"]
        tests = plan.get("selected")
        if isinstance(tests, list):
            selected = str(len(tests))
        fallback = json.dumps(plan.get("fallback", []))
    elif (state / "fallback.json").is_file():
        record = read_object(state / "fallback.json")
        mode = "full"
        status = "passed" if record.get("exit_code") == 0 else "failed"
        fallback = "CLI unavailable; independent full native command"
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"mode={mode}\nstatus={status}\nselected-tests={selected}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
        stream.write(
            f"## Smart CI native execution\n\nMode: **{mode}**. Result: **{status}**. Planned test targets: **{selected}**.\n\n"
        )
        stream.write("Fallback:<pre>" + html.escape(fallback[:4096]) + "</pre>\n\n")
        stream.write(
            "Native failures remain failures. Target counts are not individual cases. Review the uploaded plan and execution evidence. No model calls.\n"
        )


def main():
    try:
        operation = sys.argv[1]
        if operation == "stage":
            stage()
        elif operation == "install":
            install()
        elif operation == "execute":
            return execute()
        elif operation == "summary":
            summary()
        else:
            raise ValueError("unknown Action operation")
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print(
            "Smart CI Action operation failed; see the step and native execution evidence.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
