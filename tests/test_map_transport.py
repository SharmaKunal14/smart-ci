"""An archive checksum must never substitute for producer authentication."""

import base64
import hashlib
import io
import json
import runpy
import zipfile
from pathlib import Path

import pytest

fetch = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/fetch_typescript_map.py")
)["fetch"]


def response(mutation=None):
    workflow = b"approved publisher"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../head-map.json" if mutation == "path" else "head-map.json", b"{}")
        if mutation == "extra_entry":
            z.writestr("extra.json", b"{}")
    raw = archive.getvalue()
    run = {
        "id": 10,
        "run_attempt": 1,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_sha": "a" * 40,
        "head_branch": "trusted",
        "path": ".github/workflows/map.yml",
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
    }
    artifact = {
        "id": 20,
        "name": "smartci-typescript-map-1",
        "expired": False,
        "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "created_at": "2026-01-01T00:00:00Z",
    }
    if mutation == "fork":
        run["head_repository"]["full_name"] = "attacker/repo"
    if mutation == "repository":
        run["repository"]["full_name"] = "attacker/repo"
    if mutation == "event":
        run["event"] = "pull_request"
    if mutation == "branch":
        run["head_branch"] = "untrusted"
    if mutation == "commit":
        run["head_sha"] = "b" * 40
    if mutation == "workflow":
        run["path"] = ".github/workflows/evil.yml"
    if mutation == "failed":
        run["conclusion"] = "failure"
    if mutation == "attempt":
        run["run_attempt"] = 2
    if mutation == "expired":
        artifact["expired"] = True
    if mutation == "old":
        artifact["created_at"] = "2020-01-01T00:00:00Z"
    if mutation == "future":
        artifact["created_at"] = "2030-01-01T00:00:00Z"
    if mutation == "timezone":
        artifact["created_at"] = "2026-01-01T00:00:00"
    if mutation == "size":
        artifact["size_in_bytes"] = 99_000_000
    if mutation == "archive_digest":
        artifact["digest"] = "sha256:" + "0" * 64
    if mutation == "producer_code":
        workflow = b"changed publisher"

    def request(route):
        if "/contents/" in route:
            return json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "content": base64.b64encode(workflow).decode(),
                }
            ).encode()
        if "/workflows/" in route:
            return json.dumps({"workflow_runs": [run]}).encode()
        if route.endswith("/zip"):
            return raw
        return json.dumps(
            {
                "artifacts": [artifact, artifact]
                if mutation == "duplicate"
                else [artifact]
            }
        ).encode()

    return request


def get(request):
    return fetch(
        "owner/repo",
        "a" * 40,
        "trusted",
        ".github/workflows/map.yml",
        hashlib.sha256(b"approved publisher").hexdigest(),
        request,
        now=1767225601,
    )


def test_exact_trusted_push_producer_and_archive_required():
    payload, receipt = get(response())
    assert payload == b"{}" and receipt["sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["run_id"] == 10 and receipt["attempt"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "fork",
        "repository",
        "event",
        "branch",
        "commit",
        "workflow",
        "failed",
        "attempt",
        "expired",
        "old",
        "future",
        "timezone",
        "size",
        "archive_digest",
        "producer_code",
        "duplicate",
        "path",
        "extra_entry",
    ],
)
def test_untrusted_or_invalid_artifacts_are_not_consumed(mutation):
    with pytest.raises(ValueError):
        get(response(mutation))


@pytest.mark.parametrize(
    "repository,commit",
    [("owner/repo;evil", "a" * 40), ("owner/repo", "main"), ("../other", "a" * 40)],
)
def test_untrusted_inputs_cannot_change_api_routes(repository, commit):
    with pytest.raises(ValueError):
        fetch(
            repository,
            commit,
            "trusted",
            ".github/workflows/map.yml",
            "a" * 64,
            lambda route: pytest.fail("invalid route must not be requested"),
        )


def test_workflow_keeps_fetch_credentials_out_of_application_jobs():
    render = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts/render_precomputed_benchmark.py"
        )
    )["render"]
    text = render("a" * 40)
    fetch_job, app_jobs = text.split("  fetch-map:\n", 1)[1].split("  baseline:\n", 1)
    assert "GH_TOKEN" in fetch_job and "actions: read" in fetch_job
    assert "npm install" not in fetch_job and "path: app" not in fetch_job
    assert "GH_TOKEN" not in app_jobs and "actions: write" not in text
    assert "needs: fetch-map" in app_jobs.split("  cached:\n", 1)[1]
    assert "needs: fetch-map" not in app_jobs.split("  cached:\n", 1)[0]
    assert "MAP_DIGEST: ${{ needs.fetch-map.outputs.sha256 }}" in text
    assert "'--base-map-sha256', os.environ['MAP_DIGEST']" in text
    assert "pull_request_target" not in text and "retention-days: 3" in text
    assert "full_fallback" in text and "bash scripts/test/tz.sh" in text
