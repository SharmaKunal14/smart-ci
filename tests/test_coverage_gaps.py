import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.coverage_gaps import Receipt, coverage_lines, markdown, report
from smartci.selection import Report, digest


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Coverage test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "src").mkdir()
    path = root / "src/mod.py"
    path.write_text("def value():\n    return 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    base = git(root, "rev-parse", "HEAD")
    path.write_text("def value():\n    return 2\n")
    git(root, "commit", "-qam", "head")
    return root, base, git(root, "rev-parse", "HEAD")


def xml(lines='<line number="1" hits="1"/><line number="2" hits="0"/>', path="mod.py"):
    return f'<coverage><packages><class filename="{path}"><lines>{lines}</lines></class></packages></coverage>'.encode()


def receipt(head, raw, **updates):
    return Receipt(
        schema_version="smartci.coverage-receipt.v1",
        repository="owner/repo",
        revision=head,
        environment=digest({"python": "test"}),
        coverage_sha256=hashlib.sha256(raw).hexdigest(),
        source_prefix="src",
        run_url="https://github.com/owner/repo/actions/runs/123",
        execution_scope="full",
        inventory_reconciled=True,
        test_count=1,
        exit_code=0,
    ).model_copy(update=updates)


def inspect(source, raw, proof):
    root, base, head = source
    return report(
        root, "owner/repo", base, head, digest({"python": "test"}), raw, proof
    )


def test_zero_is_measured_and_deterministic_but_never_a_selection(source):
    raw = xml()
    proof = receipt(source[2], raw)
    result = inspect(source, raw, proof)
    assert result == inspect(source, raw, proof)
    assert result["evidence_status"] == "validated_receipt"
    assert result["findings"][0]["zero_hit_lines"] == [2]
    assert result["findings"][0]["status"] == "no_observed_execution"
    assert "Add appropriate behavioral tests" in result["findings"][0]["action"]
    assert result["omission_authorized"] is False
    assert result["selection_changed"] is False
    with pytest.raises(ValidationError):
        Report.model_validate(result)


@pytest.mark.parametrize(
    "updates,status",
    [
        ({"revision": "a" * 40}, "stale_revision"),
        ({"environment": "a" * 64}, "environment_mismatch"),
        ({"repository": "other/repo"}, "repository_mismatch"),
        ({"coverage_sha256": "a" * 64}, "artifact_mismatch"),
        ({"inventory_reconciled": False}, "incomplete_execution"),
        ({"exit_code": 124}, "incomplete_execution"),
        ({"test_count": 0}, "incomplete_execution"),
    ],
)
def test_unavailable_evidence_never_becomes_zero_coverage(source, updates, status):
    raw = xml()
    result = inspect(source, raw, receipt(source[2], raw, **updates))
    assert result["evidence_status"] == status
    assert result["findings"][0]["zero_hit_lines"] == []
    assert result["findings"][0]["status"] == "evidence_unavailable"


def test_missing_evidence_is_not_zero(source):
    result = inspect(source, None, None)
    assert result["evidence_status"] == "missing"
    assert result["findings"][0]["zero_hit_lines"] == []


@pytest.mark.parametrize(
    "raw,status",
    [
        (xml(path="other.py"), "file_not_measured"),
        (xml('<line number="1" hits="1"/>'), "no_reported_executable_change"),
        (xml('<line number="2" hits="1"/>'), "observed_execution"),
    ],
)
def test_absence_exclusion_and_positive_hits_are_distinct(source, raw, status):
    result = inspect(source, raw, receipt(source[2], raw))
    assert result["findings"][0]["status"] == status
    assert result["findings"][0]["zero_hit_lines"] == []


def test_failed_complete_execution_still_reports_observations(source):
    raw = xml()
    result = inspect(source, raw, receipt(source[2], raw, exit_code=1))
    assert result["evidence_status"] == "validated_receipt"
    assert result["findings"][0]["zero_hit_lines"] == [2]


@pytest.mark.parametrize(
    "raw",
    [
        b'<!DOCTYPE coverage [<!ENTITY x "unsafe">]><coverage/>',
        b"<coverage>\0</coverage>",
        b"<coverage>",
        xml(path="../secret"),
        xml('<line number="2" hits="-1"/>'),
        xml('<line number="2" hits="0"/><line number="2" hits="1"/>'),
        b'<coverage><class filename="mod.py"/><class filename="mod.py"/></coverage>',
    ],
)
def test_unsafe_or_ambiguous_xml_cannot_flag_gaps(source, raw):
    result = inspect(source, raw, receipt(source[2], raw))
    assert result["evidence_status"] == "invalid_coverage"
    assert result["findings"][0]["zero_hit_lines"] == []


def test_xml_size_bound(monkeypatch):
    monkeypatch.setattr("smartci.coverage_gaps.MAX_XML", 4)
    with pytest.raises(ValueError):
        coverage_lines(xml(), "src")


def test_deletion_has_no_head_coverage_claim(source):
    root, _, previous = source
    (root / "src/mod.py").unlink()
    git(root, "commit", "-qam", "delete")
    head = git(root, "rev-parse", "HEAD")
    raw = xml(path="other.py")
    result = inspect((root, previous, head), raw, receipt(head, raw))
    assert result["findings"][0]["status"] == "no_head_lines"
    assert result["findings"][0]["zero_hit_lines"] == []


def test_new_source_is_reported_as_missing_when_not_measured(source):
    root, _, previous = source
    (root / "src/new.py").write_text("answer = 42\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "add")
    head = git(root, "rev-parse", "HEAD")
    raw = xml()
    result = inspect((root, previous, head), raw, receipt(head, raw))
    assert result["findings"][0]["status"] == "file_not_measured"


def test_cli_emits_advisory_and_rejects_input_overwrite(source, tmp_path, monkeypatch):
    from smartci.cli import main

    root, base, head = source
    env = tmp_path / "profile.json"
    env.write_text(json.dumps({"python": "test"}))
    output, audit = tmp_path / "report.json", tmp_path / "audit.md"
    argv = [
        "smartci",
        "coverage-gaps",
        "--repo",
        str(root),
        "--repository",
        "owner/repo",
        "--base",
        base,
        "--head",
        head,
        "--environment",
        str(env),
        "--output",
        str(output),
        "--audit",
        str(audit),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0
    assert json.loads(output.read_text())["evidence_status"] == "missing"
    argv[argv.index("--output") + 1] = str(env)
    assert main() == 2
    assert json.loads(env.read_text()) == {"python": "test"}


def test_markdown_escapes_untrusted_content():
    value = markdown({"path": "<script>alert(1)</script>"})
    assert "<script>" not in value and "&lt;script&gt;" in value


def test_generation_workflow_is_retired():
    workflow = Path(".github/workflows/textual-generated-test.yml").read_text()
    assert workflow.count("if: ${{ false }}") == 3
