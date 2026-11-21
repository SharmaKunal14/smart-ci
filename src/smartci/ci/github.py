"""Bounded GitHub artifact reads. Call only in a job that executes no PR code."""

import hashlib
import io
import json
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from urllib.parse import quote

from .models import Baseline, Context

LIMIT = 32 * 1024 * 1024


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise TypeError("invalid API object")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def array_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("invalid API array")
    return list(value)


def api(route: str) -> bytes:
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ["gh", "api", "--hostname", "github.com", route],
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "GH_HOST": "github.com"},
            timeout=45,
            check=False,
        )
        if result.returncode:
            raise ValueError("GitHub artifact access unavailable")
        output.seek(0)
        raw = output.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("artifact response exceeds limit")
        return raw


def download_baseline(
    context: Context, workflow: str, request: Callable[[str], bytes] = api
) -> Baseline:
    prefix = f"repos/{context.repository}"
    branch = object_value(
        json.loads(
            request(prefix + "/branches/" + quote(context.default_branch, safe=""))
        )
    )
    if (
        branch.get("protected") is not True
        or branch.get("name") != context.default_branch
    ):
        raise ValueError("baseline branch is not protected")
    runs = object_value(
        json.loads(
            request(
                prefix
                + "/actions/workflows/"
                + quote(workflow.rsplit("/", 1)[-1], safe="")
                + "/runs?event=push&status=success&head_sha="
                + context.base
                + "&per_page=20"
            )
        )
    )
    for item in array_value(runs.get("workflow_runs", []))[:20]:
        run = object_value(item)
        if (
            run.get("event") != "push"
            or run.get("conclusion") != "success"
            or run.get("head_sha") != context.base
            or run.get("head_branch") != context.default_branch
            or run.get("path") != workflow
            or object_value(run.get("repository", {})).get("full_name")
            != context.repository
            or object_value(run.get("head_repository", {})).get("full_name")
            != context.repository
            or type(run.get("id")) is not int
            or type(run.get("run_attempt")) is not int
        ):
            continue
        run_id, attempt = run["id"], run["run_attempt"]
        artifacts = object_value(
            json.loads(
                request(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")
            )
        )
        name = f"smartci-baseline-{context.profile}-{attempt}"
        matches = [
            object_value(a)
            for a in array_value(artifacts.get("artifacts", []))[:100]
            if object_value(a).get("name") == name
            and object_value(a).get("expired") is False
        ]
        if len(matches) != 1:
            continue
        artifact = matches[0]
        size = artifact.get("size_in_bytes")
        if (
            type(artifact.get("id")) is not int
            or type(size) is not int
            or not 0 < size <= LIMIT
        ):
            raise ValueError("invalid artifact metadata")
        raw = request(f"{prefix}/actions/artifacts/{artifact['id']}/zip")
        if (
            len(raw) > LIMIT
            or artifact.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError("artifact digest mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != 1
                or entries[0].filename != "baseline.json"
                or entries[0].file_size > LIMIT
            ):
                raise ValueError("invalid baseline archive")
            with archive.open(entries[0]) as stream:
                payload = stream.read(LIMIT + 1)
            if len(payload) > LIMIT:
                raise ValueError("baseline exceeds limit")
        baseline = Baseline.model_validate_json(payload)
        if baseline.context.run_id != run_id or baseline.context.run_attempt != attempt:
            raise ValueError("producer identity mismatch")
        return baseline
    raise ValueError("no eligible baseline artifact")
