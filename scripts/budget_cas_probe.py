"""Verify GitHub's conditional write using a permanently disabled probe ledger."""

import json
import os
from pathlib import Path

from smartci.investigation.budget import BudgetError, Ledger
from smartci.investigation.github_budget import GitHubBudget
from smartci.investigation.http import HTTPS, Reply, Transport
from smartci.reports import atomic_write
from smartci.selection import digest


class RecordingTransport:
    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self.statuses: list[int] = []

    def request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> Reply:
        reply = self.inner.request(method, path, body)
        if method == "PUT":
            self.statuses.append(reply.status)
        return reply


def probe(transport: RecordingTransport) -> dict[str, object]:
    store = GitHubBudget(
        transport, "SharmaKunal14/smart-ci", "codex/model-budget-disabled-probe"
    )
    first, version = store.read()
    second, stale_version = store.read()
    if (
        first.campaign != "disabled-probe"
        or first.enabled
        or first.reservations
        or second != first
        or stale_version != version
    ):
        raise ValueError("probe requires an unchanged disabled empty ledger")
    first.cap_micro_usd = 4_900_000 if first.cap_micro_usd == 5_000_000 else 5_000_000
    store.replace(first, version)
    try:
        store.replace(second, stale_version)
    except BudgetError:
        if transport.statuses != [200, 409] and transport.statuses != [200, 422]:
            raise ValueError("expected an explicit stale write rejection") from None
    else:
        raise ValueError("stale ledger write was accepted")
    current, current_version = store.read()
    if current != first or current_version == version:
        raise ValueError("persisted budget does not match accepted write")
    try:
        Ledger(store, "disabled-probe").reserve(digest("probe"), 0, digest("probe"))
    except BudgetError:
        pass
    else:
        raise ValueError("disabled ledger admitted a call")
    return {
        "schema_version": "smartci.budget-probe.v1",
        "before": version,
        "after": current_version,
        "write_statuses": transport.statuses,
        "disabled_admission_rejected": True,
        "model_calls": 0,
        "enabled": current.enabled,
        "reservations": len(current.reservations),
    }


def main() -> None:
    transport = RecordingTransport(HTTPS("api.github.com", os.environ["GITHUB_TOKEN"]))
    report = probe(transport) | {
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "workflow_sha": os.environ["GITHUB_SHA"],
    }
    atomic_write(Path("budget-probe.json"), json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
