"""Contracts for the initial TypeScript 5 / Vitest 3 native profile."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartci.contracts import Contract, Inventory, TestUnit
from smartci.selection import Graph


class TypeScriptConfig(Contract):
    projects: list[str] = Field(min_length=1, max_length=20)
    full_paths: list[str] = Field(default_factory=list, max_length=1000)
    must_run: list[str] = Field(default_factory=list, max_length=1000)

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
    typescript: str
    node: str


class TypeScriptSnapshot(Contract):
    graph: Graph
    inventory: Inventory
    files: list[str]
    widened: list[str]
    gaps: list[str]
    analyzed: list[str]
    provenance: dict[str, str]
    digest: str = ""


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
