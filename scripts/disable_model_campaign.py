"""Disable the existing approved campaign. Never initialize or replenish it."""

import os

from smartci.investigation.github_budget import GitHubBudget
from smartci.investigation.http import HTTPS


def main():
    store = GitHubBudget(
        HTTPS("api.github.com", os.environ.get("GITHUB_TOKEN", "")),
        "SharmaKunal14/smart-ci",
        "codex/model-budget-textual-public-20261123",
    )
    campaign, version = store.read()
    if campaign.campaign != "textual-public-20261123":
        raise ValueError("campaign mismatch")
    if campaign.enabled:
        campaign.enabled = False
        store.replace(campaign, version)
    current, _ = store.read()
    if current.enabled:
        raise ValueError("campaign disablement not confirmed")
    print("Campaign disabled; all reservations retained.", flush=True)


if __name__ == "__main__":
    main()
