import base64
import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "seed_adapter", ROOT / "examples/abseil/cache_seed_run.py"
)
assert SPEC and SPEC.loader
seed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed)
REVISION = "a" * 40
NOW = datetime.fromisoformat("2026-11-26T12:00:00+00:00").timestamp()


@pytest.fixture
def evidence():
    policy = json.loads((ROOT / "examples/abseil/cache-publisher.json").read_bytes())
    raw = b"reviewed workflow"
    policy["workflow_digest"] = hashlib.sha256(raw).hexdigest()
    definition = {
        "encoding": "base64",
        "type": "file",
        "content": base64.b64encode(raw).decode(),
    }
    run = {
        "id": 42,
        "run_attempt": 2,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_sha": REVISION,
        "head_branch": policy["branch"],
        "path": policy["workflow"],
        "repository": {"full_name": policy["repository"]},
        "head_repository": {"full_name": policy["repository"]},
        "created_at": "2026-11-26T11:50:00Z",
    }
    return policy, definition, run


def discover(evidence, *, revision=REVISION):
    policy, definition, run = evidence
    calls = []

    def request(route):
        calls.append(route)
        payload = definition if "/contents/" in route else {"workflow_runs": [run]}
        return json.dumps(payload).encode()

    result = seed.discover(policy, revision, request=request, now=NOW)
    assert len(calls) == 2
    assert f"?ref={revision}" in calls[0]
    assert f"head_sha={revision}" in calls[1]
    return result


def test_discovers_exact_approved_base_and_attempt(evidence):
    assert discover(evidence) == {"run_id": 42, "run_attempt": 2}


@pytest.mark.parametrize(
    "key,value",
    [
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_sha", "b" * 40),
        ("head_branch", "unreviewed-branch"),
        ("path", ".github/workflows/another.yml"),
        ("repository", {"full_name": "attacker/fork"}),
        ("head_repository", {"full_name": "attacker/fork"}),
        ("head_repository", None),
        ("id", True),
        ("run_attempt", True),
        ("id", -1),
        ("run_attempt", 0),
        ("created_at", "2026-11-26T12:01:00Z"),
        ("created_at", "2026-11-18T12:00:00Z"),
        ("created_at", "2026-11-26T11:50:00"),
        ("created_at", "invalid"),
        ("created_at", None),
    ],
)
def test_untrusted_run_cannot_authorize_cache(evidence, key, value):
    evidence[2][key] = value
    with pytest.raises(ValueError, match="no approved"):
        discover(evidence)


def test_modified_publisher_workflow_rejected(evidence):
    evidence[1]["content"] = base64.b64encode(b"modified").decode()
    with pytest.raises(ValueError, match="workflow is not approved"):
        discover(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("repository", "owner/repo?untrusted=1"),
        ("workflow", "../../other.yml"),
        ("event", "pull_request"),
        ("max_age_seconds", True),
        ("max_age_seconds", 604801),
        ("unknown", "extra"),
    ],
)
def test_policy_rejected_before_network(evidence, key, value):
    evidence[0][key] = value
    with pytest.raises(ValueError, match="invalid"):
        seed.discover(
            evidence[0], REVISION, request=lambda _: pytest.fail("network used")
        )


def test_revision_injection_rejected_before_network(evidence):
    with pytest.raises(ValueError, match="revision"):
        seed.discover(
            evidence[0], "main&other=1", request=lambda _: pytest.fail("network used")
        )


def test_duplicate_or_oversized_metadata_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        seed.parse_object(b'{"id":1,"id":2}')
    with pytest.raises(ValueError, match="exceeds"):
        seed.parse_object(b" " * (seed.MAX_METADATA + 1))


def test_api_output_bound_and_failure_redaction(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nhead -c 2097153 /dev/zero\n")
    gh.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    with pytest.raises(ValueError, match="exceeds"):
        seed.api("repos/test/repo")
    gh.write_text("#!/bin/sh\necho sensitive >&2\nexit 1\n")
    with pytest.raises(ValueError, match="unavailable") as error:
        seed.api("repos/test/repo")
    assert "sensitive" not in str(error)


def test_workflows_use_discovered_run_without_planner_install():
    for arm in ("candidate", "control"):
        workflow = (ROOT / f"examples/abseil/cache-pr-{arm}-workflow.yml").read_text()
        assert "REVIEWED_SEED_RUN_ID" not in workflow
        assert "run-id: ${{ steps.seed.outputs.run_id }}" in workflow
        assert "native-cache-receipt-${{ steps.seed.outputs.run_attempt }}" in workflow
        block = workflow.split("        id: seed\n", 1)[1].split("      - name:", 1)[0]
        assert "python3 tool/examples/abseil/cache_seed_run.py" in block
        assert "steps.install" not in block
        shell = "\n".join(
            line[10:] for line in block.split("        run: |\n", 1)[1].splitlines()
        )
        subprocess.run(["bash", "-n"], input=shell, text=True, check=True)
