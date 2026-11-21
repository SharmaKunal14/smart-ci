"""Fetch an authenticated map in a read-only job that executes no application code.

Uses only the standard library and preinstalled gh, so retrieval needs no Python
package installation. Trust inputs must come from pinned CI control configuration,
not PR files. The approved publisher's exact bytes are checked at the base commit.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

LIMIT = 32 * 1024 * 1024
REPOSITORY = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"


def api(route: str) -> bytes:
    with tempfile.TemporaryFile() as output:
        completed = subprocess.run(
            ["gh", "api", "--hostname", "github.com", route],
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "GH_HOST": "github.com"},
            timeout=45,
            check=False,
        )
        if completed.returncode:
            raise ValueError("artifact service unavailable")
        output.seek(0)
        data = output.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("artifact response too large")
        return data


def fetch(
    repository: str,
    commit: str,
    branch: str,
    workflow: str,
    workflow_digest: str,
    request: Callable[[str], bytes] = api,
    now: float | None = None,
) -> tuple[bytes, dict[str, object]]:
    if (
        re.fullmatch(REPOSITORY, repository) is None
        or re.fullmatch(r"[a-f0-9]{40}", commit) is None
        or re.fullmatch(r"\.github/workflows/[A-Za-z0-9_-]+\.ya?ml", workflow) is None
        or re.fullmatch(r"[a-f0-9]{64}", workflow_digest) is None
        or not branch
        or len(branch) > 200
    ):
        raise ValueError("invalid trusted producer identity")
    prefix = f"repos/{repository}"
    definition = json.loads(request(f"{prefix}/contents/{workflow}?ref={commit}"))
    if definition.get("encoding") != "base64" or definition.get("type") != "file":
        raise ValueError("missing publisher definition")
    raw = base64.b64decode("".join(definition["content"].split()), validate=True)
    if hashlib.sha256(raw).hexdigest() != workflow_digest:
        raise ValueError("publisher definition not approved")
    runs = json.loads(
        request(
            f"{prefix}/actions/workflows/{quote(workflow.rsplit('/', 1)[1], safe='')}/runs"
            f"?event=push&status=success&head_sha={commit}&per_page=20"
        )
    )
    clock = time.time() if now is None else now
    for run in runs.get("workflow_runs", [])[:20]:
        if (
            run.get("event") != "push"
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("head_sha") != commit
            or run.get("head_branch") != branch
            or run.get("path") != workflow
            or run.get("repository", {}).get("full_name") != repository
            or run.get("head_repository", {}).get("full_name") != repository
            or type(run.get("id")) is not int
            or run["id"] <= 0
            or type(run.get("run_attempt")) is not int
            or run["run_attempt"] <= 0
        ):
            continue
        run_id, attempt = run["id"], run["run_attempt"]
        candidates = json.loads(
            request(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")
        )
        matches = [
            a
            for a in candidates.get("artifacts", [])[:100]
            if a.get("name") == f"smartci-typescript-map-{attempt}"
            and a.get("expired") is False
        ]
        if len(matches) != 1:
            continue
        artifact = matches[0]
        created_at = datetime.fromisoformat(artifact["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("artifact timestamp lacks timezone")
        created = created_at.timestamp()
        if not 0 <= clock - created <= 7 * 24 * 3600:
            raise ValueError("expired or future map")
        if (
            type(artifact.get("id")) is not int
            or artifact["id"] <= 0
            or type(artifact.get("size_in_bytes")) is not int
            or not 0 < artifact["size_in_bytes"] <= LIMIT
        ):
            raise ValueError("invalid artifact metadata")
        archive = request(f"{prefix}/actions/artifacts/{artifact['id']}/zip")
        if (
            len(archive) > LIMIT
            or artifact.get("digest") != "sha256:" + hashlib.sha256(archive).hexdigest()
        ):
            raise ValueError("artifact integrity mismatch")
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            entries = zipped.infolist()
            if (
                len(entries) != 1
                or entries[0].filename != "head-map.json"
                or entries[0].is_dir()
                or entries[0].flag_bits & 1
                or entries[0].file_size > LIMIT
            ):
                raise ValueError("invalid map archive")
            with zipped.open(entries[0]) as stream:
                payload = stream.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise ValueError("map too large")
        return payload, {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "run_id": run_id,
            "attempt": attempt,
            "commit": commit,
            "artifact_id": artifact["id"],
        }
    raise ValueError("no trusted map for this exact base")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in (
        "repository",
        "commit",
        "branch",
        "workflow",
        "tool-repository",
        "tool-ref",
    ):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--publisher-template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if (
            re.fullmatch(REPOSITORY, args.tool_repository) is None
            or re.fullmatch(r"[a-f0-9]{40}", args.tool_ref) is None
        ):
            raise ValueError("immutable tool identity required")
        template = (
            args.publisher_template.read_text()
            .replace("TOOL_REPOSITORY", args.tool_repository)
            .replace("TOOL_COMMIT", args.tool_ref)
        )
        payload, receipt = fetch(
            args.repository,
            args.commit,
            args.branch,
            args.workflow,
            hashlib.sha256(template.encode()).hexdigest(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(payload)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        print(json.dumps({"status": "miss", "reason": "UNTRUSTED_OR_UNAVAILABLE_MAP"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
