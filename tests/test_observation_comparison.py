import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "observation_comparison",
    Path(__file__).parents[1] / "examples/textual/compare_observation.py",
)
assert SPEC and SPEC.loader
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)

XML = b"""<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1">
<testcase classname="tests.test_app" name="passed"/>
<testcase classname="tests.test_app" name="regression"><failure>expected defect</failure></testcase>
<testcase classname="tests.test_app" name="platform"><skipped type="pytest.skip" message="unsupported platform">reason</skipped></testcase>
</testsuite></testsuites>"""


def write(path, value):
    path.write_text(json.dumps(value))


def resign(value):
    value.pop("digest", None)
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.fixture
def pair(tmp_path):
    run = {
        "status": "completed",
        "event": "pull_request",
        "run_attempt": 1,
        "head_sha": "b" * 40,
        "created_at": "2026-11-22T10:00:00Z",
        "html_url": "https://example.invalid/run/1",
    }
    jobs = []
    for i, mode in enumerate(("native", "observe-scoped")):
        directory = tmp_path / f"textual-{mode}-1"
        directory.mkdir()
        write(
            directory / "execution.json",
            {
                "base": "a" * 40,
                "head": "b" * 40,
                "mode": mode,
                "execution": "full",
                "targets": None,
                "planning_error": None,
                "exit_code": 1,
            },
        )
        (directory / "junit.xml").write_bytes(XML)
        jobs.append(
            {
                "name": mode,
                "status": "completed",
                "conclusion": "failure",
                "id": i + 1,
                "html_url": f"https://example.invalid/job/{i + 1}",
                "started_at": f"2026-11-22T10:00:0{i + 1}Z",
                "completed_at": f"2026-11-22T10:00:{10 + 2 * i}Z",
            }
        )
    observation = {
        "schema": "smartci.runtime-observation.v2",
        "engine": "monitoring",
        "commit": "b" * 40,
        "complete": False,
        "omission_authorized": False,
        "case_count": 3,
        "exit_code": 1,
        "observer_sha256": "c" * 64,
    }
    resign(observation)
    write(tmp_path / "textual-observe-scoped-1/observation.json", observation)
    write(tmp_path / "run.json", run)
    write(tmp_path / "jobs.json", {"jobs": jobs})
    return tmp_path


def test_full_pair_preserves_regression_and_measures_complete_feedback(pair):
    report = comparison.compare(pair, "observe-scoped")
    assert report["jobs"]["native"]["failed_cases"] == ["tests.test_app::regression"]
    assert report["comparison"] == {
        "case_identities_outcomes_and_skips_equal": True,
        "mismatched_cases": [],
        "observer_extra_feedback_seconds": 2.0,
        "total_runner_seconds": 19.0,
        "actual_test_omissions": 0,
        "selective_ci_savings_demonstrated": False,
    }


@pytest.mark.parametrize(
    "defect", ["different_case", "changed_skip_reason", "different_outcome"]
)
def test_equal_counts_do_not_hide_different_outcomes(pair, defect):
    path = pair / "textual-observe-scoped-1/junit.xml"
    xml = path.read_bytes()
    if defect == "different_case":
        xml = xml.replace(b'name="passed"', b'name="other"')
    elif defect == "changed_skip_reason":
        xml = xml.replace(b"unsupported platform", b"different reason")
    else:
        xml = xml.replace(b'failures="1"', b'failures="0"').replace(
            b'errors="0"', b'errors="1"'
        )
        xml = xml.replace(b"<failure>", b"<error>").replace(b"</failure>", b"</error>")
    path.write_bytes(xml)
    report = comparison.compare(pair, "observe-scoped")
    assert report["comparison"]["case_identities_outcomes_and_skips_equal"] is False
    assert len(report["comparison"]["mismatched_cases"]) == (
        2 if defect == "different_case" else 1
    )


@pytest.mark.parametrize(
    "defect",
    [
        "stale_head",
        "subset",
        "collection_error",
        "missing_target",
        "digest",
        "unfinished",
        "rerun",
    ],
)
def test_invalid_evidence_cannot_be_reported_as_a_valid_pair(pair, defect):
    file = pair / "textual-observe-scoped-1/execution.json"
    if defect in {"unfinished", "rerun"}:
        file = pair / "run.json"
    elif defect == "digest":
        file = pair / "textual-observe-scoped-1/observation.json"
    value = json.loads(file.read_text())
    field, replacement = {
        "stale_head": ("head", "d" * 40),
        "subset": ("execution", "subset"),
        "collection_error": ("exit_code", 2),
        "missing_target": ("targets", []),
        "digest": ("case_count", 4),
        "unfinished": ("status", "in_progress"),
        "rerun": ("run_attempt", 2),
    }[defect]
    value[field] = replacement
    write(file, value)
    with pytest.raises(ValueError):
        comparison.compare(pair, "observe-scoped")


@pytest.mark.parametrize(
    "raw",
    [
        XML.replace(b'tests="3"', b'tests="99"'),
        XML.replace(b'name="passed"', b'name="regression"'),
        b"<!DOCTYPE testsuites><testsuites/>",
        "<!DOCTYPE testsuites><testsuites/>".encode("utf-16"),
    ],
)
def test_malformed_ambiguous_or_incomplete_junit_is_rejected(raw):
    with pytest.raises(ValueError):
        comparison.junit(raw)
