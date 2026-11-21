"""Pure conservative selection over explicitly declared, versioned evidence."""

import fnmatch
import hashlib
import json
from collections import deque
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Contract, Identifier, Inventory, Policy, TestUnit


class Graph(Contract):
    commit: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    complete: bool
    unsupported: bool = False
    owners: dict[str, Identifier]
    dependencies: dict[Identifier, list[Identifier]]
    tests: dict[Identifier, Identifier]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        nodes = set(self.dependencies)
        if any(n not in nodes for deps in self.dependencies.values() for n in deps):
            raise ValueError("dangling dependency")
        if any(n not in nodes for n in [*self.owners.values(), *self.tests.values()]):
            raise ValueError("dangling owner")
        for path in self.owners:
            TestUnit.relative_path(path)
        if (
            len(nodes) > 100_000
            or sum(map(len, self.dependencies.values())) > 1_000_000
        ):
            raise ValueError("graph exceeds limits")
        return self


class Changes(Contract):
    base: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    head: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    paths: list[str] = Field(max_length=100_000)

    @model_validator(mode="after")
    def valid_paths(self) -> Self:
        for path in self.paths:
            TestUnit.relative_path(path)
        return self


class Coverage(Contract):
    commit: str
    environment: str
    complete: bool
    files: dict[Identifier, list[str]]

    @model_validator(mode="after")
    def valid_paths(self) -> Self:
        for paths in self.files.values():
            for path in paths:
                TestUnit.relative_path(path)
        return self


class SelectionPolicy(Policy):
    full_paths: list[str] = Field(default_factory=list, max_length=1000)
    require_coverage: bool = False


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"] = "1"
    engine_version: Literal["0.1.0"] = "0.1.0"
    comparison: dict[str, str] = Field(default_factory=dict)
    mode: Literal["full", "subset"]
    execution: Literal["full", "subset"]
    selected: list[str]
    reasons: dict[str, list[str]]
    omitted: dict[str, str]
    fallback: list[str]
    warnings: list[str]
    evidence: dict[str, str]
    digest: str = ""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def finish(report: Report) -> Report:
    report.digest = digest(report.model_dump(exclude={"digest"}))
    return report


def fallback(code: str, inventory: Inventory | None = None) -> Report:
    ids = sorted(t.id for t in inventory.tests) if inventory else []
    return finish(
        Report(
            mode="full",
            execution="full",
            selected=ids,
            reasons={i: [code] for i in ids},
            omitted={},
            fallback=[code],
            warnings=[],
            evidence={},
        )
    )


RISK_NAMES = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "Dockerfile",
    "conftest.py",
}
RISK_PARTS = {".github", ".smartci", "migrations", "config", "schemas"}


def select(
    changes: Changes,
    inventory: Inventory,
    base: Graph,
    head: Graph,
    policy: SelectionPolicy,
    coverage: Coverage | None = None,
) -> Report:
    ids = {t.id for t in inventory.tests}
    evidence = {
        "changes": digest(changes.model_dump()),
        "inventory": digest(inventory.model_dump()),
        "base_graph": digest(base.model_dump()),
        "head_graph": digest(head.model_dump()),
        "policy": digest(policy.model_dump()),
    }
    warnings: list[str] = []

    def full(code: str) -> Report:
        result = fallback(code, inventory)
        result.comparison = {"base": changes.base, "head": changes.head}
        result.evidence = evidence
        result.warnings = warnings
        return finish(result)

    if len({x.repository for x in (changes, inventory, base, head, policy)}) != 1:
        return full("REPOSITORY_MISMATCH")
    if not inventory.complete or not base.complete or not head.complete:
        return full("INCOMPLETE_EVIDENCE")
    if base.unsupported or head.unsupported:
        return full("UNSUPPORTED_ANALYSIS")
    if base.commit != changes.base or head.commit != changes.head:
        return full("STALE_GRAPH")
    if set(head.tests) != ids or not set(policy.must_run) <= ids:
        return full("INVENTORY_MISMATCH")
    for path in changes.paths:
        if (
            path.split("/")[-1] in RISK_NAMES
            or set(path.split("/")) & RISK_PARTS
            or path.endswith((".lock", ".sql"))
            or any(fnmatch.fnmatchcase(path, p) for p in policy.full_paths)
        ):
            return full("RISK_PATH")
    coverage_valid = (
        coverage is not None
        and coverage.complete
        and coverage.commit == changes.base
        and coverage.environment == inventory.environment
        and coverage.repository == inventory.repository
        and set(coverage.files) <= ids
    )
    if coverage is not None:
        evidence["coverage"] = digest(coverage.model_dump())
    if not coverage_valid:
        if policy.require_coverage:
            return full("REQUIRED_COVERAGE_MISSING_OR_STALE")
        if coverage is not None:
            warnings.append("OPTIONAL_COVERAGE_IGNORED")
    changed = set(changes.paths)
    affected: set[str] = set()
    for path in changed:
        owners = {g.owners[path] for g in (base, head) if path in g.owners}
        if not owners:
            return full("UNMAPPED_PATH")
        affected.update(owners)
    reverse: dict[str, set[str]] = {}
    for graph in (base, head):
        for node, dependencies in graph.dependencies.items():
            for dependency in dependencies:
                reverse.setdefault(dependency, set()).add(node)
    queue = deque(sorted(affected))
    while queue:
        for dependant in sorted(reverse.get(queue.popleft(), set())):
            if dependant not in affected:
                affected.add(dependant)
                queue.append(dependant)
    reasons: dict[str, list[str]] = {}
    for test in inventory.tests:
        why = []
        if test.id in policy.must_run:
            why.append("MUST_RUN")
        if test.path in changed or test.id not in base.tests:
            why.append("NEW_OR_CHANGED_TEST")
        for graph in (base, head):
            owner = graph.tests.get(test.id)
            if owner in affected:
                why.append(f"IMPACTED_COMPONENT:{owner}")
        if (
            coverage_valid
            and coverage is not None
            and changed.intersection(coverage.files.get(test.id, []))
        ):
            why.append("COVERAGE_MATCH")
        if why:
            reasons[test.id] = sorted(set(why))
    if not reasons:
        return full("EMPTY_SELECTION")
    return finish(
        Report(
            comparison={"base": changes.base, "head": changes.head},
            mode="subset",
            execution="full" if policy.mode == "shadow" else "subset",
            selected=sorted(reasons),
            reasons=reasons,
            omitted={
                i: "NO_IMPACT_FOUND_UNDER_RECORDED_EVIDENCE"
                for i in sorted(ids - reasons.keys())
            },
            fallback=[],
            warnings=warnings,
            evidence=evidence,
        )
    )
