"""Find an approved base-only seed without installing the Smart CI planner.

This is the independent baseline's cache provenance check. Policy comes from the
pinned tool checkout, never PR source. Downloaded receipts and cache contents still
need their separate identity and integrity checks before native cache admission.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

MAX_METADATA = 2 * 1024 * 1024


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate seed metadata key")
        result[key] = value
    return result


def parse_object(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_METADATA:
        raise ValueError("seed metadata exceeds limit")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise TypeError("seed metadata must be an object")
    return {str(key): item for key, item in value.items()}


def api(route: str) -> bytes:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
        if key in os.environ
    }
    with subprocess.Popen(
        ["gh", "api", "--hostname", "github.com", route],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**environment, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"},
    ) as process:
        assert process.stdout is not None
        timer = threading.Timer(45, process.kill)
        timer.start()
        try:
            raw = process.stdout.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise ValueError("seed metadata exceeds limit")
            if process.wait() != 0:
                raise ValueError("seed metadata unavailable")
            return raw
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            timer.cancel()
            timer.join()


def discover(
    policy: dict[str, object],
    revision: str,
    *,
    request: Callable[[str], bytes] = api,
    now: float | None = None,
) -> dict[str, int]:
    patterns = {
        "repository": r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}",
        "branch": r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}",
        "workflow": r"\.github/workflows/[A-Za-z0-9_-]+\.ya?ml",
        "workflow_digest": r"[a-f0-9]{64}",
        "artifact_prefix": r"[A-Za-z0-9_-]{1,100}",
    }
    if set(policy) != {*patterns, "schema_version", "event", "max_age_seconds"}:
        raise ValueError("invalid seed publisher fields")
    for name, pattern in patterns.items():
        value = policy[name]
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise ValueError("invalid seed publisher identity")
    age = policy["max_age_seconds"]
    if (
        policy["schema_version"] != "1"
        or policy["event"] != "push"
        or type(age) is not int
        or not isinstance(age, int)
        or not 1 <= age <= 604800
        or re.fullmatch(r"[a-f0-9]{40}", revision) is None
    ):
        raise ValueError("invalid base-only seed policy or revision")
    repository, workflow = str(policy["repository"]), str(policy["workflow"])
    prefix = f"repos/{repository}"
    definition = parse_object(request(f"{prefix}/contents/{workflow}?ref={revision}"))
    content = definition.get("content")
    if (
        definition.get("encoding") != "base64"
        or definition.get("type") != "file"
        or not isinstance(content, str)
        or hashlib.sha256(
            base64.b64decode("".join(content.split()), validate=True)
        ).hexdigest()
        != policy["workflow_digest"]
    ):
        raise ValueError("seed workflow is not approved")
    runs = parse_object(
        request(
            f"{prefix}/actions/workflows/{workflow.rsplit('/', 1)[1]}/runs"
            f"?event=push&status=success&head_sha={revision}&per_page=20"
        )
    ).get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 20:
        raise ValueError("invalid seed run listing")
    clock = time.time() if now is None else now
    for run in runs:
        if not isinstance(run, dict):
            raise TypeError("invalid seed run metadata")
        if any(
            run.get(key) != value
            for key, value in {
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "head_sha": revision,
                "head_branch": policy["branch"],
                "path": workflow,
            }.items()
        ):
            continue
        if any(
            not isinstance(run.get(key), dict)
            or run[key].get("full_name") != repository
            for key in ("repository", "head_repository")
        ):
            continue
        run_id, attempt = run.get("id"), run.get("run_attempt")
        if (
            type(run_id) is not int
            or type(attempt) is not int
            or run_id <= 0
            or attempt <= 0
        ):
            continue
        created = run.get("created_at")
        if not isinstance(created, str):
            continue
        try:
            timestamp = datetime.fromisoformat(created)
        except ValueError:
            continue
        if timestamp.tzinfo is None or not 0 <= clock - timestamp.timestamp() <= age:
            continue
        return {"run_id": run_id, "run_attempt": attempt}
    raise ValueError("no approved successful seed for the exact PR base")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publisher", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.publisher.open("rb") as stream:
        policy = parse_object(stream.read(MAX_METADATA + 1))
    result = discover(policy, args.revision)
    with args.output.open("x") as output:
        output.write(json.dumps(result, sort_keys=True) + "\n")
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with Path(github_output).open("a") as output:
            output.writelines(f"{key}={value}\n" for key, value in result.items())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError):
        # Provider output can contain sensitive data. Cache unavailability is
        # handled by the workflow's independent full-suite execution path.
        raise SystemExit("Approved base cache seed unavailable") from None
