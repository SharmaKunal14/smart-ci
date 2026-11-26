"""Language-neutral investigation contracts; no model controls policy or authority."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

from smartci.contracts import Digest, Inventory, TestUnit
from smartci.selection import Changes, Graph, SelectionPolicy, digest


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Inputs(Strict):
    schema_version: Literal["smartci.investigation-input.v1"] = (
        "smartci.investigation-input.v1"
    )
    changes: Changes
    inventory: Inventory
    base: Graph
    head: Graph
    policy: SelectionPolicy
    sources: dict[str, dict[str, Digest]]
    unresolved: list[str] = Field(max_length=100_000)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            len(
                {
                    x.repository
                    for x in (
                        self.changes,
                        self.inventory,
                        self.base,
                        self.head,
                        self.policy,
                    )
                }
            )
            != 1
        ):
            raise ValueError("repository mismatch")
        if (self.base.commit, self.head.commit) != (
            self.changes.base,
            self.changes.head,
        ):
            raise ValueError("revision mismatch")
        if set(self.sources) != {self.base.commit, self.head.commit}:
            raise ValueError("source revisions mismatch")
        for graph in (self.base, self.head):
            if set(self.sources[graph.commit]) != set(graph.owners):
                raise ValueError("source catalog must exactly match graph owners")
        if len(self.unresolved) != len(set(self.unresolved)):
            raise ValueError("duplicate unresolved issue")
        return self

    def identity(self) -> str:
        return digest(self.model_dump())


class Limits(Strict):
    steps: int = Field(default=24, ge=1, le=64)
    source_bytes: int = Field(default=1_048_576, ge=1, le=4_194_304)
    response_bytes: int = Field(default=262_144, ge=1, le=1_048_576)
    seconds: int = Field(default=60, ge=1, le=120)


class Location(Strict):
    revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    path: str = Field(max_length=1024)

    @field_validator("path")
    @classmethod
    def path_valid(cls, value: str) -> str:
        return TestUnit.relative_path(value)


class Inspect(Location):
    kind: Literal["inspect"]
    adapter: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class ReadSource(Location):
    kind: Literal["read_source"]
    start: int = Field(ge=1, le=100_000)
    lines: int = Field(ge=1, le=80)


class Search(Strict):
    kind: Literal["search_paths"]
    query: str = Field(min_length=1, max_length=128)


class Query(Location):
    kind: Literal["query_graph"]


class Propose(Location):
    kind: Literal["propose"]
    target: str = Field(max_length=1024)
    evidence: Digest
    line: int = Field(ge=1, le=100_000)
    relation: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @field_validator("target")
    @classmethod
    def target_valid(cls, value: str) -> str:
        return TestUnit.relative_path(value)


class Unresolved(Strict):
    kind: Literal["unresolved"]
    # A label is data, never an instruction or a policy waiver.
    label: str = Field(min_length=1, max_length=256)


class Finish(Strict):
    kind: Literal["finish"]


type Action = Annotated[
    Inspect | ReadSource | Search | Query | Propose | Unresolved | Finish,
    Field(discriminator="kind"),
]


class ActionEnvelope(RootModel[Action]):
    pass


class ImportFact(Strict):
    target: str
    line: int


class Observation(Location):
    source_digest: Digest
    adapter: str
    adapter_digest: Digest
    facts: list[ImportFact]
    facts_truncated: bool
    evidence: Digest


class Accepted(Propose):
    verifier: str
    verifier_digest: Digest
    source_digest: Digest
    already_recorded: bool
