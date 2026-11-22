"""Durable pre-call reservations. Failed/uncertain calls never replenish budget."""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from smartci.contracts import Digest
from smartci.selection import digest

from .models import Strict


class BudgetError(ValueError):
    """Admission failed; do not invoke a model or automatically retry."""


class RateCard(Strict):
    model: Literal["gpt-6.2-astra"] = "gpt-6.2-astra"
    # Micro-USD per token equals USD per million tokens. Reserve the higher
    # 30-minute cache-write input rate even though explicit caching is disabled.
    input_micro_usd: Literal[10] = 10
    output_micro_usd: Literal[40] = 40
    checked_at: datetime
    source: Literal["https://developers.openai.com/api/docs/pricing"] = (
        "https://developers.openai.com/api/docs/pricing"
    )

    def fresh(self, now: datetime) -> None:
        if self.checked_at.tzinfo is None or not timedelta(
            0
        ) <= now - self.checked_at <= timedelta(hours=24):
            raise BudgetError("pricing requires revalidation")


class Reservation(Strict):
    investigation: Digest
    slot: int = Field(ge=0, lt=4)
    request_digest: Digest
    input_limit: int = Field(default=5000, ge=1, le=5000)
    output_limit: int = Field(default=1000, ge=1, le=1000)
    micro_usd: int = Field(ge=1)
    # Usage is optional; reservation is always retained, including on timeouts.
    usage: dict[Literal["input_tokens", "output_tokens"], int] | None = None


class Campaign(Strict):
    schema_version: Literal["smartci.model-budget.v1"] = "smartci.model-budget.v1"
    campaign: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    enabled: bool = False
    rates: RateCard
    # Initialization is a separate, explicit operation. Invocation never creates
    # or resets a ledger. The approval limits cannot be increased by CLI flags.
    cap_micro_usd: int = Field(default=5_000_000, ge=1, le=5_000_000)
    max_calls: int = Field(default=24, ge=1, le=24)
    max_investigations: int = Field(default=6, ge=1, le=6)
    max_input_tokens: int = Field(default=120_000, ge=1, le=120_000)
    max_output_tokens: int = Field(default=24_000, ge=1, le=24_000)
    reservations: list[Reservation] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        records = self.reservations
        if len({(r.investigation, r.slot) for r in records}) != len(records):
            raise ValueError("duplicate reservation")
        if (
            len(records) > self.max_calls
            or len({r.investigation for r in records}) > self.max_investigations
            or sum(r.input_limit for r in records) > self.max_input_tokens
            or sum(r.output_limit for r in records) > self.max_output_tokens
            or sum(r.micro_usd for r in records) > self.cap_micro_usd
        ):
            raise ValueError("campaign exceeds approval")
        for r in records:
            if (
                r.micro_usd
                != r.input_limit * self.rates.input_micro_usd
                + r.output_limit * self.rates.output_micro_usd
            ):
                raise ValueError("reservation price mismatch")
            if r.usage is not None and (
                set(r.usage) != {"input_tokens", "output_tokens"}
                or any(type(v) is not int or v < 0 for v in r.usage.values())
                or r.usage["input_tokens"] > r.input_limit
                or r.usage["output_tokens"] > r.output_limit
            ):
                raise ValueError("usage exceeds reservation")
        return self


class Store(Protocol):
    def read(self) -> tuple[Campaign, str]: ...
    def replace(self, campaign: Campaign, expected_version: str) -> None: ...


class Ledger:
    def __init__(self, store: Store, expected_campaign: str) -> None:
        self.store = store
        self.expected_campaign = expected_campaign

    def current(self) -> tuple[Campaign, str]:
        campaign, version = self.store.read()
        campaign = Campaign.model_validate_json(campaign.model_dump_json())
        if campaign.campaign != self.expected_campaign:
            raise BudgetError("campaign identity mismatch")
        return campaign, version

    def reserve(
        self,
        investigation: str,
        slot: int,
        request_digest: str,
        *,
        now: datetime | None = None,
    ) -> Reservation:
        campaign, version = self.current()
        if not campaign.enabled:
            raise BudgetError("campaign disabled")
        campaign.rates.fresh(now or datetime.now(UTC))
        reservation = Reservation(
            investigation=investigation,
            slot=slot,
            request_digest=request_digest,
            micro_usd=5000 * campaign.rates.input_micro_usd
            + 1000 * campaign.rates.output_micro_usd,
        )
        candidate = campaign.model_dump(mode="json")
        candidate["reservations"].append(reservation.model_dump(mode="json"))
        updated = Campaign.model_validate_json(json.dumps(candidate))
        # A stale write or lost acknowledgment stops admission. Never assume a
        # reservation succeeded and never send a duplicate request to recover it.
        self.store.replace(updated, version)
        return reservation

    def record_usage(
        self, reservation: Reservation, input_tokens: int, output_tokens: int
    ) -> None:
        campaign, version = self.current()
        records = [
            r
            for r in campaign.reservations
            if (r.investigation, r.slot)
            == (reservation.investigation, reservation.slot)
        ]
        if len(records) != 1 or records[0] != reservation:
            raise BudgetError("reservation changed")
        if (
            type(input_tokens) is not int
            or type(output_tokens) is not int
            or not 0 <= input_tokens <= reservation.input_limit
            or not 0 <= output_tokens <= reservation.output_limit
        ):
            campaign.enabled = False
            self.store.replace(campaign, version)
            raise BudgetError("unexpected usage; campaign disabled")
        records[0].usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        self.store.replace(campaign, version)

    def identity(self) -> str:
        campaign, _ = self.current()
        return digest(campaign.model_dump(mode="json"))
