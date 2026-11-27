"""Advisory changed-line coverage. Never dependency or test-omission evidence.

The caller supplies a receipt from a trusted runner after checking its execution
and native inventory. Hashes bind artifacts; they do not authenticate a publisher.
"""

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import Digest, TestUnit
from .git_changes import changes_from_git, git
from .selection import digest

MAX_XML = 16 * 1024 * 1024
MAX_LINES = 500_000


class Receipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: Literal["smartci.coverage-receipt.v1"]
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    environment: Digest
    coverage_sha256: Digest
    source_prefix: str
    run_url: str = Field(
        pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[1-9][0-9]{0,19}$"
    )
    execution_scope: Literal["full", "subset"]
    inventory_reconciled: bool
    test_count: int = Field(ge=0, le=100_000)
    exit_code: int = Field(ge=0, le=255)

    @field_validator("source_prefix")
    @classmethod
    def prefix(cls, value: str) -> str:
        return "" if not value else TestUnit.relative_path(value)


def coverage_lines(raw: bytes, prefix: str) -> dict[str, dict[int, int]]:
    """Read coverage.py/Cobertura line records without expanding XML entities."""
    if (
        len(raw) > MAX_XML
        or b"\0" in raw
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        raise ValueError("invalid coverage XML")
    raw.decode("utf-8")
    root = ET.fromstring(raw)
    if root.tag != "coverage":
        raise ValueError("expected coverage XML")
    files: dict[str, dict[int, int]] = {}
    count = 0
    for entry in root.iter("class"):
        name = TestUnit.relative_path(entry.attrib["filename"])
        path = TestUnit.relative_path(f"{prefix}/{name}" if prefix else name)
        if path in files or len(files) >= 10_000:
            raise ValueError("ambiguous or excessive coverage files")
        lines: dict[int, int] = {}
        for line in entry.iter("line"):
            number, hits = line.attrib["number"], line.attrib["hits"]
            if not re.fullmatch(r"[1-9][0-9]{0,5}", number) or not re.fullmatch(
                r"[0-9]{1,12}", hits
            ):
                raise ValueError("invalid coverage count")
            n = int(number)
            if n in lines or count >= MAX_LINES:
                raise ValueError("duplicate or excessive coverage lines")
            lines[n] = int(hits)
            count += 1
        files[path] = lines
    if not files:
        raise ValueError("empty coverage")
    return files


def changed_lines(repo: Path, base: str, head: str, path: str) -> list[int]:
    raw = git(
        repo,
        "--no-replace-objects",
        "--literal-pathspecs",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--unified=0",
        base,
        head,
        "--",
        path,
    ).decode("utf-8")
    lines: set[int] = set()
    for start, length in re.findall(
        r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw, re.MULTILINE
    ):
        first, count = int(start), int(length) if length else 1
        if count > MAX_LINES or len(lines) + count > MAX_LINES:
            raise ValueError("changed lines exceed limit")
        lines.update(range(first, first + count))
    return sorted(lines)


def report(
    repo: Path,
    repository: str,
    base: str,
    head: str,
    environment: str,
    coverage: bytes | None,
    receipt: Receipt | None,
) -> dict[str, object]:
    changes = changes_from_git(repo, base, head, repository)
    if changes.base != base or len(changes.paths) > 1000:
        raise ValueError("exact bounded comparison required")
    status = "missing"
    files: dict[str, dict[int, int]] = {}
    if receipt is not None and coverage is not None:
        if receipt.repository != repository:
            status = "repository_mismatch"
        elif receipt.revision != head:
            status = "stale_revision"
        elif receipt.environment != environment:
            status = "environment_mismatch"
        elif (
            not receipt.inventory_reconciled
            or receipt.test_count == 0
            or receipt.exit_code not in {0, 1}
        ):
            status = "incomplete_execution"
        elif hashlib.sha256(coverage).hexdigest() != receipt.coverage_sha256:
            status = "artifact_mismatch"
        else:
            try:
                files = coverage_lines(coverage, receipt.source_prefix)
                status = "validated_receipt"
            except (ValueError, KeyError, ET.ParseError):
                status = "invalid_coverage"
    findings = []
    for path in changes.paths:
        changed = changed_lines(repo, base, head, path)
        measured = files.get(path) if status == "validated_receipt" else None
        executable = sorted(set(changed) & measured.keys()) if measured else []
        zero = [n for n in executable if measured is not None and measured[n] == 0]
        finding = (
            "evidence_unavailable"
            if status != "validated_receipt"
            else "no_head_lines"
            if not changed
            else "file_not_measured"
            if measured is None
            else "no_reported_executable_change"
            if not executable
            else "no_observed_execution"
            if zero
            else "observed_execution"
        )
        findings.append(
            {
                "path": path,
                "status": finding,
                "changed_head_lines": changed,
                "reported_executable_changed_lines": executable,
                "zero_hit_lines": zero,
                "action": "Add appropriate behavioral tests and rerun coverage."
                if zero
                else None,
            }
        )
    result: dict[str, object] = {
        "schema_version": "smartci.coverage-gaps.v1",
        "repository": repository,
        "comparison": {"base": base, "head": head},
        "environment": environment,
        "evidence_status": status,
        "evidence": receipt.model_dump() if receipt else None,
        "findings": findings,
        "omission_authorized": False,
        "selection_changed": False,
        "limits": [
            "Zero hits mean no observed execution in this run and environment, not that no test exists.",
            "Full execution does not validate behavior it never exercises; line hits do not prove assertion quality.",
            "Missing lines, excluded code and deleted lines are not measured zero coverage.",
            "Receipts must come from a trusted runner; local hashes and bindings do not authenticate their publisher.",
        ],
    }
    result["digest"] = digest(result)
    return result


def markdown(value: dict[str, object]) -> str:
    return (
        "# Changed-code coverage\n\n"
        "Review changed executable lines with no observed execution and add appropriate tests. "
        "This report does not generate tests or authorize omissions. Missing or stale evidence "
        "is not measured zero coverage. A full suite cannot validate behavior it never exercises.\n\n"
        f"<pre>{html.escape(json.dumps(value, indent=2, sort_keys=True))}</pre>\n"
    )
