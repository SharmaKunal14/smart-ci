"""Contracts for version-bounded compiler and native Vitest profiles."""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartci.contracts import Contract, Digest, Inventory, TestUnit
from smartci.selection import Graph


class ReviewedSkip(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    path: str
    case: Digest
    source_digest: Digest
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_path(self) -> Self:
        TestUnit.relative_path(self.path)
        return self


class NativeProject(BaseModel):
    """Explicit native project scope; never replace the repository's test config."""

    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["vitest5-typescript7"]
    directory: str
    configuration: str
    project: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    lockfile: Literal["pnpm-lock.yaml"]
    timezone: str = "UTC"
    reviewed_skips: list[ReviewedSkip] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def valid(self) -> Self:
        for path in (self.directory, self.configuration):
            TestUnit.relative_path(path)
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("unknown timezone") from exc
        if len({r.case for r in self.reviewed_skips}) != len(self.reviewed_skips):
            raise ValueError("duplicate skip review")
        return self


class TypeScriptConfig(Contract):
    projects: list[str] = Field(min_length=1, max_length=20)
    full_paths: list[str] = Field(default_factory=list, max_length=1000)
    must_run: list[str] = Field(default_factory=list, max_length=1000)
    native_project: NativeProject | None = None

    @model_validator(mode="after")
    def paths(self) -> Self:
        for path in [*self.projects, *self.must_run]:
            TestUnit.relative_path(path)
        if len(set(self.projects)) != len(self.projects):
            raise ValueError("duplicate project")
        return self


class Analysis(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    dependencies: dict[str, list[str]]
    widened: list[str]
    gaps: list[str]
    analyzed: list[str]
    warnings: list[str] = Field(default_factory=list)
    typescript: str
    node: str
    native_tests: list[str] | None = Field(default=None, max_length=100_000)


class TypeScriptSnapshot(Contract):
    graph: Graph
    inventory: Inventory
    files: list[str]
    widened: list[str]
    gaps: list[str]
    analyzed: list[str]
    provenance: dict[str, str]
    digest: str = ""
    warnings: list[str] = Field(default_factory=list)


class NativeResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: Literal["passed", "failed", "incomplete"]
    files: list[str]
    cases: int
    failed: int
    failed_cases: list[str] = Field(default_factory=list)
    skipped: int
    returncode: int
    duration_seconds: float
    reviewed_skips: list[str] = Field(default_factory=list)


class ListedFile(BaseModel):
    model_config = ConfigDict(strict=True)
    file: str
    projectName: str | None = None


class Assertion(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str
    ancestorTitles: list[str]
    status: str


class NativeFile(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    assertionResults: list[Assertion]


class NativeReport(BaseModel):
    model_config = ConfigDict(strict=True)
    success: bool
    testResults: list[NativeFile]
