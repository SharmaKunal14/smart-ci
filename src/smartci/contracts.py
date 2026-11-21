"""Version-one, strict, bounded contracts; unknown fields fail closed."""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,199}$")
]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"]
    repository: Identifier


class TestUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Identifier
    runner: Literal["pytest", "vitest", "maven"]
    granularity: Literal["case", "file", "class"]
    path: str = Field(min_length=1, max_length=1024)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "\\" in value
            or ":" in value
            or any(ord(c) < 32 for c in value)
            or any(part in ("", ".", "..") for part in value.split("/"))
            or str(PurePosixPath(value)) != value
        ):
            raise ValueError("expected a normalized repository-relative POSIX path")
        return value


class Inventory(Contract):
    complete: bool
    environment: Digest
    tests: list[TestUnit] = Field(max_length=100_000)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({t.id for t in self.tests}) != len(self.tests):
            raise ValueError("duplicate test IDs")
        return self


class Policy(Contract):
    mode: Literal["shadow", "selective"] = "shadow"
    must_run: list[Identifier] = Field(default_factory=list, max_length=100_000)
    unknown_evidence: Literal["full"] = "full"
    allow_source_excerpts: bool = False


class Decision(Contract):
    mode: Literal["full", "subset"]
    selected: list[Identifier] = Field(max_length=100_000)
    reasons: list[str] = Field(min_length=1, max_length=1000)
    policy_digest: Digest

    @model_validator(mode="after")
    def valid_selection(self) -> Self:
        if len(set(self.selected)) != len(self.selected):
            raise ValueError("duplicate selected IDs")
        if self.mode == "subset" and not self.selected:
            raise ValueError("empty subsets are forbidden")
        return self


class Execution(Contract):
    status: Literal["complete", "incomplete"]
    outcome: Literal["passed", "failed", "error"]
    decision_digest: Digest

    @model_validator(mode="after")
    def incomplete_cannot_pass(self) -> Self:
        if self.status == "incomplete" and self.outcome == "passed":
            raise ValueError("incomplete execution cannot pass")
        return self


class Investigation(Contract):
    baseline_digest: Digest
    max_calls: int = Field(ge=1, le=4)
    max_input_tokens: int = Field(ge=1, le=20_000)
    max_output_tokens: int = Field(ge=1, le=3000)


class ToolRequest(Contract):
    tool: Literal[
        "inspect_change",
        "search_repository",
        "query_dependencies",
        "lookup_test_history",
        "request_validation",
        "submit_evidence",
    ]
    target: Identifier
    call_id: Identifier


class Evidence(Contract):
    baseline_digest: Digest
    additions: list[Identifier] = Field(max_length=100_000)
    source_digests: list[Digest] = Field(min_length=1, max_length=1000)
    status: Literal["provisional"] = "provisional"


CONTRACTS: dict[str, type[BaseModel]] = {
    "inventory": Inventory,
    "policy": Policy,
    "decision": Decision,
    "execution": Execution,
    "investigation": Investigation,
    "tool-request": ToolRequest,
    "evidence": Evidence,
}
