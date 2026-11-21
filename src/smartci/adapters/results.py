"""Detailed local execution reports; distinct from the Phase 1 execution summary."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartci.contracts import Contract, Digest, Identifier

from .runners import Outcome

Status = Literal["passed", "failed", "incomplete"]


class Attempt(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    suite: Identifier
    mode: Literal["full", "subset"]
    status: Status
    expected: list[Identifier] = Field(min_length=1, max_length=100_000)
    observed: dict[Identifier, Outcome]
    targets: dict[Identifier, str]
    returncode: int
    duration: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        expected = set(self.expected)
        if len(expected) != len(self.expected) or set(self.targets) != expected:
            raise ValueError("invalid expected unit mapping")
        if not set(self.observed) <= expected:
            raise ValueError("unknown observed unit")
        if self.status != "incomplete":
            if set(self.observed) != expected or "skipped" in self.observed.values():
                raise ValueError("incomplete attempt cannot be complete")
            if self.status == "passed" and (
                self.returncode != 0 or "failed" in self.observed.values()
            ):
                raise ValueError("failed attempt cannot pass")
            if self.status == "failed" and "failed" not in self.observed.values():
                raise ValueError("failed attempt requires a test failure")
        return self


class RunReport(Contract):
    status: Status
    execution: Literal["full", "subset"]
    fallback: list[str] = Field(max_length=10)
    inventory_digest: Digest
    decision_digest: Digest | None
    attempts: list[Attempt] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def outcome(self) -> Self:
        failed = any("failed" in a.observed.values() for a in self.attempts)
        final = {a.suite: a for a in self.attempts}
        if self.status == "passed" and (
            failed or any(a.status != "passed" for a in final.values())
        ):
            raise ValueError("unverified or failed tests cannot pass")
        if self.status == "failed" and not failed:
            raise ValueError("failed report requires a test failure")
        if self.execution == "full" and any(a.mode != "full" for a in final.values()):
            raise ValueError("full execution requires full final attempts")
        return self
