"""Persist the shared ledger with GitHub Contents API conditional replacement."""

import base64
import json
import re
from urllib.parse import quote

from .budget import BudgetError, Campaign
from .http import Transport


class GitHubBudget:
    def __init__(self, transport: Transport, repository: str, branch: str) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository
        ) or not re.fullmatch(r"codex/model-budget-[a-z0-9-]+", branch):
            raise ValueError("invalid budget repository or branch")
        self.transport, self.branch = transport, branch
        self.path = f"/repos/{repository}/contents/budget.json"

    def read(self) -> tuple[Campaign, str]:
        response = self.transport.request(
            "GET", self.path + "?ref=" + quote(self.branch, safe="")
        )
        if response.status != 200:
            raise BudgetError("shared budget unavailable")
        value = json.loads(response.body)
        if (
            not isinstance(value, dict)
            or value.get("type") != "file"
            or value.get("encoding") != "base64"
            or value.get("path") != "budget.json"
            or not isinstance(value.get("sha"), str)
            or not re.fullmatch(r"[a-f0-9]{40}", value["sha"])
            or not isinstance(value.get("content"), str)
        ):
            raise BudgetError("invalid budget artifact")
        raw = base64.b64decode("".join(value["content"].split()), validate=True)
        if len(raw) > 65536:
            raise BudgetError("budget artifact exceeds limit")
        return Campaign.model_validate_json(raw), value["sha"]

    def replace(self, campaign: Campaign, expected_version: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{40}", expected_version):
            raise BudgetError("invalid budget version")
        campaign = Campaign.model_validate_json(campaign.model_dump_json())
        response = self.transport.request(
            "PUT",
            self.path,
            {
                "message": "Record model budget reservation or usage",
                "branch": self.branch,
                "sha": expected_version,
                "content": base64.b64encode(
                    campaign.model_dump_json().encode()
                ).decode(),
            },
        )
        if response.status != 200:
            raise BudgetError("budget update unconfirmed; no model call permitted")
