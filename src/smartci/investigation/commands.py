"""Offline by default; live invocation requires an existing durable budget."""

import argparse
import json
import os
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.reports import atomic_write
from smartci.selection import digest

from .adapters import PythonImports
from .broker import Broker
from .budget import Ledger
from .engine import Provider, investigate
from .github_budget import GitHubBudget
from .http import HTTPS
from .models import Inputs, Limits, Location
from .openai_provider import OpenAIProvider
from .process_scripts import PythonProcessScripts
from .public_scope import validate_public_scope
from .replay import ChangeScopeReplay, DiagnosticReplay, ImportReplay


def command(args: argparse.Namespace) -> int:
    try:
        # Two complete repository graphs can exceed the small runner manifests.
        # This bound is local parsing only; the provider receives bounded actions.
        inputs = Inputs.model_validate_json(read_bounded(args.inputs, 32 * 1024 * 1024))
        locations = [
            Location(revision=inputs.head.commit, path=path) for path in args.focus
        ]
        limits = Limits()
        provider: Provider = ImportReplay(locations)
        if args.provider == "diagnostic-replay":
            provider = DiagnosticReplay()
        if args.provider == "scope-replay":
            provider = ChangeScopeReplay()
        if args.provider == "openai":
            if (
                not all(
                    (
                        args.campaign,
                        args.budget_repository,
                        args.budget_branch,
                        args.trial,
                    )
                )
                or args.data_scope != "public-github-global-openai"
            ):
                raise ValueError("live campaign and data scope required")
            if os.environ.get("SMARTCI_DISABLE_MODEL_CALLS") == "1":
                raise ValueError("model calls disabled")
            github = HTTPS("api.github.com", os.environ.get("GITHUB_TOKEN", ""))
            model = HTTPS("api.openai.com", os.environ.get("OPENAI_API_KEY", ""))
            validate_public_scope(inputs, github)
            ledger = Ledger(
                GitHubBudget(github, args.budget_repository, args.budget_branch),
                args.campaign,
            )
            provider = OpenAIProvider(
                model, ledger, digest({"input": inputs.identity(), "trial": args.trial})
            )
            limits = Limits(steps=4, seconds=120)
        report = investigate(
            inputs,
            Broker(
                args.repo,
                inputs,
                PythonImports(args.module_root),
                limits,
                additional_adapters=(PythonProcessScripts(),)
                if getattr(args, "enable_process_inspection", False) is True
                else (),
            ),
            provider,
            limits,
        )
        atomic_write(args.output, json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "model_calls": report["model_calls"],
                    "evaluation": report["evaluation_kind"],
                }
            )
        )
        return 0 if report["status"] == "finished" else 2
    except (OSError, ValueError):
        print(json.dumps({"status": "error", "code": "INVALID_INVESTIGATION_INPUT"}))
        return 2


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "investigate",
        help="bounded evidence investigation; offline by default, no test execution",
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--module-root", action="append", required=True)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=["replay", "diagnostic-replay", "scope-replay", "openai"],
        default="replay",
    )
    parser.add_argument(
        "--enable-process-inspection",
        action="store_true",
        help="register bounded positive script-argument inspection; no process execution",
    )
    parser.add_argument("--campaign")
    parser.add_argument("--budget-repository")
    parser.add_argument("--budget-branch")
    parser.add_argument("--trial", type=int, choices=range(1, 7))
    parser.add_argument("--data-scope", choices=["public-github-global-openai"])
