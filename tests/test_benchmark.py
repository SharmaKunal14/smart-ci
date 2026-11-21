"""Reject misleading performance samples rather than silently counting them."""

import json
import runpy
from pathlib import Path

import pytest

from smartci.selection import Report, finish
from smartci.typescript.collector import test_id as unit_id

validate = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/benchmark_onrecord.py")
)["validate_result"]


@pytest.fixture
def sample(tmp_path):
    proposal = finish(
        Report(
            mode="subset",
            execution="subset",
            selected=[unit_id("tests/auth.test.ts")],
            reasons={unit_id("tests/auth.test.ts"): ["IMPACTED"]},
            omitted={unit_id("tests/other.test.ts"): "NO_IMPACT"},
            fallback=[],
            warnings=[],
            evidence={},
        )
    )
    (tmp_path / "selection.json").write_text(proposal.model_dump_json())
    result = {
        "status": "passed",
        "returncode": 0,
        "files": ["tests/auth.test.ts"],
        "cases": 1,
        "failed": 0,
        "skipped": 0,
        "duration_seconds": 1.0,
    }
    data = {
        "decision_digest": proposal.digest,
        "execution": "subset",
        "fallback": [],
        "attempts": [result],
    }
    return tmp_path, data


def test_accepts_complete_subset(sample):
    path, data = sample
    (path / "run.json").write_text(json.dumps(data))
    assert validate(path, "candidate_subset")[0]["cases"] == 1


@pytest.mark.parametrize(
    "defect",
    ["digest", "full", "retry", "fallback", "wrong_file", "skipped", "failed", "empty"],
)
def test_rejects_ineligible_benchmark_samples(sample, defect):
    path, data = sample
    result = data["attempts"][0]
    if defect == "digest":
        data["decision_digest"] = "0" * 64
    elif defect == "full":
        data["execution"] = "full"
    elif defect == "retry":
        data["attempts"].append(result.copy())
    elif defect == "fallback":
        data["fallback"] = ["INCOMPLETE"]
    elif defect == "wrong_file":
        result["files"] = ["tests/other.test.ts"]
    elif defect == "empty":
        result["cases"] = 0
    else:
        result[defect] = 1
    (path / "run.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        validate(path, "candidate_subset")
