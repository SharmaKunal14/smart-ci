import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "runtime_assessment",
    Path(__file__).parents[1] / "examples/textual/assess_observation.py",
)
assert SPEC is not None and SPEC.loader is not None
assessment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assessment)


def report(shared=True):
    value = {
        "schema": "smartci.runtime-observation.v1",
        "complete": False,
        "omission_authorized": False,
        "commit": "a" * 40,
        "test_files": ["tests/test_a.py", "tests/test_b.py"],
        "case_count": 2,
        "tracked_blobs": {"src/app.py": "b" * 40},
        "contexts": {
            "tests/test_a.py": {
                "code_files": ["src/app.py"],
                "code_entries": ["src/app.py:1"],
            },
            "@shared": {"code_files": ["src/app.py"] if shared else []},
        },
    }
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


@pytest.mark.parametrize("shared", [False, True])
def test_observed_candidates_never_authorize_omissions(shared):
    result = assessment.assess(
        None, report(shared), {"commit": "c" * 40, "gaps": []}, ["src/app.py"]
    )
    candidate = result["candidates"][0]
    assert candidate["observed_call_files"] == ["tests/test_a.py"]
    assert len(candidate["candidate_files_including_shared"]) == (2 if shared else 1)
    assert candidate["omission_authorized"] is False
    assert result["execution_required"] == "full"


def test_tampered_digest_and_source_revision_are_rejected(monkeypatch):
    value = report()
    value["case_count"] = 99
    compatibility = {
        "commit": "c" * 40,
        "gaps": [{"path": "src/app.py", "line": 2, "code": "DYNAMIC_CODE"}],
    }
    with pytest.raises(ValueError, match="digest"):
        assessment.assess(None, value, compatibility, [])
    monkeypatch.setattr(assessment, "git", lambda *args: b"different blob")
    with pytest.raises(ValueError, match="revision"):
        assessment.assess(None, report(), compatibility, [])


def test_function_entry_is_not_gap_statement_coverage(monkeypatch):
    source = b"@cached\ndef loader():\n    if False:\n        exec(code)\n"
    monkeypatch.setattr(
        assessment,
        "git",
        lambda root, command, *args: source if command == "show" else b"b" * 40,
    )
    compatibility = {
        "commit": "c" * 40,
        "gaps": [{"path": "src/app.py", "line": 4, "code": "DYNAMIC_CODE"}],
    }
    result = assessment.assess(None, report(), compatibility, [])
    gap = result["gaps"][0]
    assert gap["function"] == {"name": "loader", "line": 1}
    assert gap["observed_contexts"] == ["tests/test_a.py"]
    assert gap["resolved"] is False


@pytest.mark.parametrize(
    "scope,owner,expected",
    [
        ("function", "tests/test_a.py", 1),
        ("module", "tests/test_a.py", 1),
        ("class", "tests/test_a.py", 1),
        ("package", "tests", 2),
        ("session", ".", 2),
        ("function", "@unknown", 2),
        ("unrecognized", "tests/test_a.py", 2),
    ],
)
def test_scoped_observations_are_candidates_not_omission_authority(
    scope, owner, expected
):
    value = report(False)
    value["schema"] = "smartci.runtime-observation.v2"
    value["contexts"] = {"@phase:fixture": {"code_files": ["src/app.py"]}}
    value["context_metadata"] = {
        "@phase:fixture": {"kind": "fixture_setup", "scope": scope, "owner": owner}
    }
    value.pop("digest")
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = assessment.assess(
        None, value, {"commit": "c" * 40, "gaps": []}, ["src/app.py"]
    )
    assert len(result["candidates"][0]["candidate_files_including_shared"]) == expected
    assert result["execution_required"] == "full"
    assert result["omission_authorized"] is False
