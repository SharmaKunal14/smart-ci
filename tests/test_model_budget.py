import base64
import json
import runpy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from smartci.investigation.budget import BudgetError, Campaign, Ledger, RateCard
from smartci.investigation.github_budget import GitHubBudget
from smartci.investigation.http import Reply
from smartci.selection import digest


class MemoryStore:
    def __init__(self, campaign=None):
        self.state = campaign or Campaign(
            campaign="approved",
            enabled=True,
            rates=RateCard(checked_at=datetime.now(UTC)),
        )
        self.version = 0

    def read(self):
        return self.state.model_copy(deep=True), str(self.version)

    def replace(self, campaign, expected_version):
        if expected_version != str(self.version):
            raise BudgetError("conflict")
        self.state = Campaign.model_validate_json(campaign.model_dump_json())
        self.version += 1


def test_limits_are_aggregate_and_reservations_are_not_released():
    store = MemoryStore()
    ledger = Ledger(store, "approved")
    for trial in range(6):
        for slot in range(4):
            r = ledger.reserve(digest(trial), slot, digest([trial, slot]))
            ledger.record_usage(r, 100, 10)
    assert len(store.state.reservations) == 24
    assert sum(r.micro_usd for r in store.state.reservations) == 2_160_000
    assert sum(r.input_limit for r in store.state.reservations) == 120_000
    with pytest.raises(ValidationError):
        ledger.reserve(digest(7), 0, digest("extra"))


@pytest.mark.parametrize(
    "defect",
    [
        "disabled",
        "old_price",
        "future_price",
        "wrong_campaign",
        "small_cap",
        "duplicate",
        "fifth_call",
        "seventh_investigation",
    ],
)
def test_denied_admission_does_not_write(defect):
    store = MemoryStore()
    ledger = Ledger(store, "approved")
    slot = 0
    investigation = digest("one")
    if defect == "disabled":
        store.state.enabled = False
    elif defect == "old_price":
        store.state.rates.checked_at -= timedelta(days=2)
    elif defect == "future_price":
        store.state.rates.checked_at += timedelta(days=2)
    elif defect == "wrong_campaign":
        ledger.expected_campaign = "other"
    elif defect == "small_cap":
        store.state.cap_micro_usd = 80_000
    elif defect == "duplicate":
        ledger.reserve(investigation, 0, digest("request"))
    elif defect == "fifth_call":
        slot = 4
    elif defect == "seventh_investigation":
        for trial in range(6):
            ledger.reserve(digest(trial), 0, digest(trial))
    version = store.version
    with pytest.raises(ValueError):
        ledger.reserve(investigation, slot, digest("request"))
    assert store.version == version


def test_usage_breach_disables_campaign_and_keeps_reservation():
    store = MemoryStore()
    ledger = Ledger(store, "approved")
    r = ledger.reserve(digest("one"), 0, digest("request"))
    with pytest.raises(BudgetError):
        ledger.record_usage(r, 5001, 100)
    assert store.state.enabled is False
    assert store.state.reservations == [r]


class ConditionalGitHub:
    def __init__(self):
        self.raw = MemoryStore().state.model_dump_json().encode()
        self.sha = "a" * 40
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return Reply(
                200,
                json.dumps(
                    {
                        "type": "file",
                        "path": "budget.json",
                        "encoding": "base64",
                        "sha": self.sha,
                        "content": base64.b64encode(self.raw).decode(),
                    }
                ).encode(),
            )
        if body["sha"] != self.sha:
            return Reply(409, b"{}")
        self.raw = base64.b64decode(body["content"])
        self.sha = "b" * 40
        return Reply(200, b"{}")


def test_two_writers_cannot_spend_the_same_remaining_budget():
    api = ConditionalGitHub()
    store = GitHubBudget(api, "owner/repo", "codex/model-budget-approved")
    first, version = store.read()
    second, stale_version = store.read()
    first.enabled = False
    store.replace(first, version)
    with pytest.raises(BudgetError):
        store.replace(second, stale_version)
    assert store.read()[0].enabled is False
    assert all(
        call[1].startswith("/repos/owner/repo/contents/budget.json")
        for call in api.calls
    )
    assert api.calls[2][2]["branch"] == "codex/model-budget-approved"


@pytest.mark.parametrize(
    "status,body",
    [
        (404, b"{}"),
        (200, b"[]"),
        (200, b'{"type":"symlink"}'),
        (200, b'{"type":"file","encoding":"base64","path":"budget.json","sha":1}'),
    ],
)
def test_missing_corrupt_ledger_never_initializes(status, body):
    class API:
        def request(self, method, path, data=None):
            assert method == "GET"
            return Reply(status, body)

    with pytest.raises(ValueError):
        GitHubBudget(API(), "owner/repo", "codex/model-budget-approved").read()


def test_approval_cannot_be_expanded_through_config():
    for field, value in {
        "cap_micro_usd": 5_000_001,
        "max_calls": 25,
        "max_investigations": 7,
        "max_input_tokens": 120_001,
        "max_output_tokens": 24_001,
    }.items():
        data = MemoryStore().state.model_dump(mode="json") | {field: value}
        with pytest.raises(ValidationError):
            Campaign.model_validate_json(json.dumps(data))


def test_hosted_probe_rejects_enabled_ledger_and_checks_real_conflict_status():
    module = runpy.run_path("scripts/budget_cas_probe.py")
    api = ConditionalGitHub()
    state = Campaign.model_validate_json(api.raw)
    state.campaign = "disabled-probe"
    api.raw = state.model_dump_json().encode()
    with pytest.raises(ValueError, match="disabled empty"):
        module["probe"](module["RecordingTransport"](api))
    assert all(method == "GET" for method, _, _ in api.calls)
    state.enabled = False
    api.raw = state.model_dump_json().encode()
    result = module["probe"](module["RecordingTransport"](api))
    assert result["write_statuses"] == [200, 409]
    assert result["model_calls"] == result["reservations"] == 0
    assert result["disabled_admission_rejected"]
