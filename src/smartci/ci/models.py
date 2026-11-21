"""Strict CI identity, skip policy and protected baseline contracts."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from smartci.contracts import Digest
from smartci.discovery.models import Snapshot

Commit = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
Repository = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$",
        max_length=140,
    ),
]
ComparisonStatus = Literal[
    "complete", "complete_with_expected_skips", "failed", "incomplete"
]


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Context(Strict):
    schema_version: Literal["1"] = "1"
    repository: Repository
    event: Literal["pull_request", "push", "workflow_dispatch"]
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    base: Commit
    tested: Commit
    pr_head: Commit | None = None
    ref: str = Field(max_length=256)
    default_branch: str = Field(max_length=200)
    protected: bool
    profile: Literal["linux-py314", "local-py314"] = "linux-py314"

    @model_validator(mode="after")
    def pr_identity(self) -> Self:
        if self.event == "pull_request" and self.pr_head is None:
            raise ValueError("PR identity missing")
        if self.event != "pull_request" and (
            self.pr_head is not None or self.base != self.tested
        ):
            raise ValueError("non-PR identity mismatch")
        return self


class ExpectedSkip(Strict):
    case: str = Field(min_length=1, max_length=4096)
    platform: Literal["Darwin", "Linux"]
    reason: str = Field(min_length=1, max_length=1000)
    source_digest: Digest


class ShadowPolicy(Strict):
    schema_version: Literal["1"] = "1"
    expected_skips: list[ExpectedSkip] = Field(default_factory=list, max_length=100)
    max_baseline_age_seconds: int = Field(default=604800, ge=60, le=604800)


class Comparison(Strict):
    schema_version: Literal["1"] = "1"
    context: Context
    snapshot_digest: Digest
    decision_digest: Digest
    status: ComparisonStatus
    native_exit: int
    native_cases: int = Field(ge=0, le=100_000)
    failed_cases: list[str]
    known_skips: list[str]
    unexpected_skips: list[str]
    missed_failure_files: list[str]
    baseline_eligible: bool


class Baseline(Strict):
    schema_version: Literal["1"] = "1"
    context: Context
    snapshot: Snapshot
    comparison: Comparison
    policy_digest: Digest
    created_at: int = Field(ge=1)
    expires_at: int = Field(ge=1)

    @model_validator(mode="after")
    def bindings(self) -> Self:
        c = self.context
        result = self.comparison
        if (
            c.event != "push"
            or not c.protected
            or c.ref != "refs/heads/" + c.default_branch
            or c != result.context
            or self.snapshot.graph.commit != c.tested
            or result.snapshot_digest != self.snapshot.digest
            or self.snapshot.repository != c.repository
            or not self.snapshot.graph.complete
            or not self.snapshot.inventory.complete
            or self.snapshot.provenance.gaps
            or c.profile != "linux-py314"
            or self.snapshot.provenance.environment.platform != "Linux"
            or self.snapshot.provenance.environment.implementation != "CPython"
            or not self.snapshot.provenance.environment.python.startswith("3.14.")
            or result.status != "complete"
            or not result.baseline_eligible
            or result.native_exit != 0
            or result.failed_cases
            or result.known_skips
            or result.unexpected_skips
            or result.missed_failure_files
            or result.native_cases != self.snapshot.provenance.native_case_count
            or not self.created_at < self.expires_at <= self.created_at + 604800
        ):
            raise ValueError("ineligible protected baseline")
        return self
