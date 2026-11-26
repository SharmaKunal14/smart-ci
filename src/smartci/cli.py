"""Local contracts, selection and trusted-workspace execution utilities."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .adapters.results import RunReport
from .adapters.suite import SuiteConfig, discover, execute, manifest
from .bazel import commands as bazel_commands
from .bazel.bundle import Manifest as BazelManifest
from .bazel.bundle import Profile as BazelProfile
from .bazel.collection import CaptureConfig as BazelCaptureConfig
from .bazel.execution import ExecutionConfig as BazelExecutionConfig
from .bazel.transport import Publisher as BazelPublisher
from .ci import commands as ci_commands
from .ci.models import Baseline, Comparison, Context, ShadowPolicy
from .contracts import CONTRACTS, Inventory
from .discovery.commands import collect_command, plan_command
from .discovery.models import PythonConfig, Snapshot
from .git_changes import changes_from_git
from .investigation import commands as investigation_commands
from .investigation.budget import Campaign as ModelBudget
from .investigation.models import ActionEnvelope as InvestigationAction
from .investigation.models import Inputs as InvestigationInputs
from .investigation.models import Observation as InvestigationObservation
from .reports import atomic_write, markdown
from .selection import (
    Changes,
    Coverage,
    Graph,
    Report,
    SelectionPolicy,
    digest,
    fallback,
    select,
)
from .typescript import commands as ts_commands
from .typescript.models import TypeScriptConfig, TypeScriptSnapshot

CONTRACTS.update(
    {
        "graph": Graph,
        "changes": Changes,
        "coverage": Coverage,
        "selection-policy": SelectionPolicy,
        "suite": SuiteConfig,
        "run-report": RunReport,
        "python-collector": PythonConfig,
        "snapshot": Snapshot,
        "ci-context": Context,
        "shadow-policy": ShadowPolicy,
        "shadow-comparison": Comparison,
        "baseline": Baseline,
        "typescript-collector": TypeScriptConfig,
        "typescript-snapshot": TypeScriptSnapshot,
        "investigation-input": InvestigationInputs,
        "investigation-action": InvestigationAction,
        "investigation-observation": InvestigationObservation,
        "model-budget": ModelBudget,
        "bazel-profile": BazelProfile,
        "bazel-manifest": BazelManifest,
        "bazel-capture": BazelCaptureConfig,
        "bazel-execution": BazelExecutionConfig,
        "bazel-publisher": BazelPublisher,
    }
)

MAX_BYTES = 5 * 1024 * 1024


class InputError(ValueError):
    """An untrusted manifest could not be read or validated."""


def validate_file(kind: str, path: Path) -> None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise InputError("input exceeds size limit")
        CONTRACTS[kind].model_validate_json(raw)
    except (OSError, ValidationError, ValueError) as exc:
        # Pydantic messages may contain input values: never echo them to the CLI.
        raise InputError("manifest is unreadable or invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smart CI local selection and execution"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ci_commands.add_parser(sub)
    investigation_commands.add_parser(sub)
    ts_commands.add_parser(sub)
    bazel_commands.add_parser(sub)
    validate = sub.add_parser(
        "validate", help="validate a manifest; does not run tests"
    )
    validate.add_argument("kind", choices=sorted(CONTRACTS))
    validate.add_argument("path", type=Path)
    schema = sub.add_parser("schema", help="print a version-one JSON Schema")
    schema.add_argument("kind", choices=sorted(CONTRACTS))
    selection = sub.add_parser("select", help="produce a proposal; never execute tests")
    selection.add_argument("--inventory", type=Path, required=True)
    selection.add_argument("--policy", type=Path, required=True)
    selection.add_argument("--base-graph", type=Path, required=True)
    selection.add_argument("--head-graph", type=Path, required=True)
    selection.add_argument("--coverage", type=Path)
    selection.add_argument("--changes", type=Path)
    selection.add_argument("--repo", type=Path)
    selection.add_argument("--base")
    selection.add_argument("--head")
    selection.add_argument("--output", type=Path, required=True)
    selection.add_argument("--audit", type=Path, required=True)
    explain = sub.add_parser("explain", help="render and integrity-check a report")
    explain.add_argument("path", type=Path)
    collection = sub.add_parser(
        "collect", help="collect Python evidence in a trusted clean checkout"
    )
    collection.add_argument("--config", type=Path, required=True)
    collection.add_argument("--repo", type=Path, required=True)
    collection.add_argument(
        "--python", help="target interpreter with the Smart CI pytest plugin installed"
    )
    collection.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory outside the target repository",
    )
    collection.add_argument(
        "--run-full", action="store_true", help="also run the unfiltered native suite"
    )
    planning = sub.add_parser(
        "plan", help="plan from automatic collector snapshots; never execute tests"
    )
    planning.add_argument("--repo", type=Path, required=True)
    planning.add_argument("--base-snapshot", type=Path, required=True)
    planning.add_argument("--head-snapshot", type=Path, required=True)
    planning.add_argument("--policy", type=Path, required=True)
    planning.add_argument("--output", type=Path, required=True)
    planning.add_argument("--audit", type=Path, required=True)
    for command in ("discover", "run"):
        adapter = sub.add_parser(
            command, help="execute trusted local discovery/test code"
        )
        adapter.add_argument("--config", type=Path, required=True)
        adapter.add_argument("--output", type=Path, required=True)
        if command == "run":
            adapter.add_argument("--decision", type=Path)
    args = parser.parse_args()
    if args.command == "bazel":
        return bazel_commands.command(args)
    if args.command == "investigate":
        return investigation_commands.command(args)
    if args.command == "typescript":
        return ts_commands.command(args)
    if args.command == "shadow":
        return ci_commands.command(args)
    if args.command == "collect":
        return collect_command(args)
    if args.command == "plan":
        return plan_command(args)
    if args.command in ("discover", "run"):
        return adapter_command(args)
    if args.command == "select":
        return select_command(args)
    if args.command == "explain":
        try:
            report = Report.model_validate_json(read_input(args.path))
            if digest(report.model_dump(exclude={"digest"})) != report.digest:
                raise ValueError("digest mismatch")
            print(markdown(report))
            return 0
        except (OSError, ValueError):
            print(json.dumps({"status": "error", "code": "INVALID_REPORT"}))
            return 2
    if args.command == "schema":
        print(json.dumps(CONTRACTS[args.kind].model_json_schema(), indent=2))
        return 0
    try:
        validate_file(args.kind, args.path)
    except InputError:
        print(json.dumps({"status": "error", "code": "INVALID_MANIFEST"}))
        return 2
    print(json.dumps({"status": "valid", "kind": args.kind}))
    return 0


def read_input(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InputError("input exceeds limit")
    return data


def select_command(args: argparse.Namespace) -> int:
    inventory: Inventory | None = None
    try:
        inventory = Inventory.model_validate_json(read_input(args.inventory))
        policy = SelectionPolicy.model_validate_json(read_input(args.policy))
        base_graph = Graph.model_validate_json(read_input(args.base_graph))
        head_graph = Graph.model_validate_json(read_input(args.head_graph))
        if args.changes is not None:
            if args.repo is not None or args.base is not None or args.head is not None:
                raise ValueError("ambiguous inputs")
            changes = Changes.model_validate_json(read_input(args.changes))
        else:
            if args.repo is None or args.base is None or args.head is None:
                raise ValueError("missing Git comparison")
            changes = changes_from_git(
                args.repo, args.base, args.head, inventory.repository
            )
        coverage = (
            Coverage.model_validate_json(read_input(args.coverage))
            if args.coverage
            else None
        )
        report = select(changes, inventory, base_graph, head_graph, policy, coverage)
    except (OSError, ValueError):
        report = fallback("INVALID_OR_UNAVAILABLE_INPUT", inventory)
    try:
        inputs = [
            args.inventory,
            args.policy,
            args.base_graph,
            args.head_graph,
            args.coverage,
            args.changes,
        ]
        outputs = [args.output.resolve(), args.audit.resolve()]
        if outputs[0] == outputs[1] or any(
            p is not None and p.resolve() in outputs for p in inputs
        ):
            raise ValueError("output aliases input")
        # Publish the decision last; consumers must check the exit code and digest.
        atomic_write(args.audit, markdown(report))
        atomic_write(
            args.output,
            json.dumps(report.model_dump(), sort_keys=True, indent=2) + "\n",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {"status": "error", "code": "REPORT_WRITE_FAILED", "execution": "full"}
            )
        )
        return 2
    print(
        json.dumps(
            {
                "mode": report.mode,
                "execution": report.execution,
                "digest": report.digest,
            }
        )
    )
    return 0


def adapter_command(args: argparse.Namespace) -> int:
    try:
        if args.output.resolve() in {
            args.config.resolve(),
            getattr(args, "decision", None) and args.decision.resolve(),
        }:
            raise ValueError("output aliases input")
        suite = discover(args.config)
        if args.command == "discover":
            atomic_write(args.output, manifest(suite))
            print(
                json.dumps(
                    {"status": "discovered", "units": len(suite.inventory.tests)}
                )
            )
            return 0
        decision = None
        invalid = False
        if args.decision is not None:
            try:
                decision = Report.model_validate_json(read_input(args.decision))
            except (OSError, ValueError):
                invalid = True
        result = execute(suite, decision)
        if invalid:
            result["fallback"] = ["INVALID_OR_UNAVAILABLE_DECISION"]
        atomic_write(args.output, json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "execution": result["execution"],
                    "fallback": result["fallback"],
                }
            )
        )
        return {"passed": 0, "failed": 1, "incomplete": 2}[str(result["status"])]
    except (OSError, ValueError):
        print(json.dumps({"status": "incomplete", "code": "ADAPTER_OR_OUTPUT_ERROR"}))
        return 2
