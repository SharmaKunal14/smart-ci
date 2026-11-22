"""Offline command only: no endpoint, credential lookup, shell tool or live provider."""

import argparse
import json
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.reports import atomic_write

from .adapters import PythonImports
from .broker import Broker
from .engine import investigate
from .models import Inputs, Limits, Location
from .replay import ImportReplay


def command(args: argparse.Namespace) -> int:
    try:
        inputs = Inputs.model_validate_json(read_bounded(args.inputs))
        locations = [
            Location(revision=inputs.head.commit, path=path) for path in args.focus
        ]
        limits = Limits()
        report = investigate(
            inputs,
            Broker(args.repo, inputs, PythonImports(args.module_root), limits),
            ImportReplay(locations),
            limits,
        )
        atomic_write(args.output, json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "model_calls": 0,
                    "evaluation": "offline_plumbing_only",
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
        help="offline replay of bounded evidence investigation; no test execution",
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--module-root", action="append", required=True)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
