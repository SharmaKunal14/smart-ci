"""Companion contracts keep the original graph schema backwards compatible."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smartci.contracts import Contract, Digest, Identifier, Inventory, TestUnit
from smartci.selection import Graph, digest

COLLECTOR_VERSION: Literal["python-ast-1"] = "python-ast-1"


class PythonConfig(Contract):
    source_roots: list[str] = Field(min_length=1, max_length=16)
    test_roots: list[str] = Field(min_length=1, max_length=16)
    granularity: Literal["case", "file"] = "file"
    allowed_plugins: list[Identifier] = Field(default_factory=list, max_length=32)
    external_module_overrides: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("source_roots", "test_roots")
    @classmethod
    def roots(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate root")
        for value in values:
            if value != ".":
                TestUnit.relative_path(value)
        return sorted(values)

    @field_validator("allowed_plugins")
    @classmethod
    def plugins(cls, values: list[str]) -> list[str]:
        return sorted(set(values))

    @field_validator("external_module_overrides")
    @classmethod
    def external_overrides(cls, values: list[str]) -> list[str]:
        if any(len(v) > 128 or not v.isidentifier() for v in values):
            raise ValueError("top-level external module names required")
        return sorted(set(values))


class Gap(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    code: Identifier
    path: str | None = None
    line: int = Field(default=0, ge=0)


class Edge(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source: str
    target: str
    kind: Literal["import", "bounded_import", "package_init", "fixture", "resource"]
    line: int = Field(default=0, ge=0)


class ImportFact(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    path: str
    line: int = Field(ge=1)
    module: str = Field(max_length=512)
    resolution: Literal[
        "local",
        "bounded_local",
        "stdlib",
        "distribution",
        "optional_absent",
        "unresolved",
        "reviewed_external_override",
    ]


class Environment(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    python: str
    implementation: str
    platform: str
    machine: str
    abi: str
    observer_digest: Digest
    distributions: dict[str, str]
    external_modules: list[str]
    available_modules: list[str]
    stdlib: list[str]
    native_roots: dict[str, str | None]
    import_hooks: list[str]
    hook_hashes: dict[str, Digest]
    ambient: dict[str, Digest]
    configuration: dict[str, Digest]

    def identity(self) -> str:
        # Lookup answers depend on the revision's imports, not just the environment.
        return digest(self.model_dump(exclude={"native_roots", "available_modules"}))


class Provenance(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    collector: Literal["python-ast-1"] = COLLECTOR_VERSION
    implementation_digest: Digest
    config: PythonConfig
    environment: Environment
    sources: dict[str, Digest]
    edges: list[Edge] = Field(max_length=1_000_000)
    imports: list[ImportFact] = Field(max_length=1_000_000)
    gaps: list[Gap] = Field(max_length=100_000)
    native_targets: dict[Identifier, str]
    native_cases_digest: Digest
    native_case_count: int = Field(ge=1, le=100_000)
    plugins: list[str]


class Snapshot(Contract):
    graph: Graph
    inventory: Inventory
    provenance: Provenance
    digest: Digest

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if digest(self.model_dump(exclude={"digest"})) != self.digest:
            raise ValueError("snapshot digest mismatch")
        p = self.provenance
        if (
            len(
                {
                    self.repository,
                    self.graph.repository,
                    self.inventory.repository,
                    p.config.repository,
                }
            )
            != 1
        ):
            raise ValueError("repository mismatch")
        if self.inventory.environment != p.environment.identity():
            raise ValueError("environment mismatch")
        ids = {test.id for test in self.inventory.tests}
        if set(self.graph.tests) != ids or set(p.native_targets) != ids:
            raise ValueError("test mapping mismatch")
        if self.graph.complete != (not p.gaps) or self.graph.unsupported != bool(
            p.gaps
        ):
            raise ValueError("gap status mismatch")
        for path in p.sources:
            TestUnit.relative_path(path)
        if not set(self.graph.owners) <= set(p.sources):
            raise ValueError("owner without source digest")
        for edge in p.edges:
            if (
                edge.source not in self.graph.owners
                or edge.target not in self.graph.owners
            ):
                raise ValueError("edge without source")
            if (
                self.graph.owners[edge.target]
                not in self.graph.dependencies[self.graph.owners[edge.source]]
            ):
                raise ValueError("provenance edge missing from graph")
        for test in self.inventory.tests:
            if self.graph.owners.get(test.path) != self.graph.tests[test.id]:
                raise ValueError("test owner mismatch")
        return self
