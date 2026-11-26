"""Execute a freshly derived plan using reviewed, credential-free native commands.

The caller authenticates configuration and map provenance. This module never
accepts a PR-supplied plan, executes a shell, or treats a green planner as a test
result. Run repository code only on an isolated runner.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import StrictBool, StrictInt

from smartci.contracts import Digest

from .audit import NativeInventory
from .bundle import (
    LIMITS,
    MAX_MANIFEST_BYTES,
    Profile,
    StrictModel,
    canonical,
    load,
    read_bounded,
    sha256,
)
from .collection import CaptureCommand, run_command
from .events import summarize_bytes, unique_object
from .graph import QueryError
from .planning import parse_tree


class ExecutionConfig(StrictModel):
    schema_version: Literal["1"]
    profile: Profile
    full: CaptureCommand
    subset: CaptureCommand
    subset_options_digest: Digest


class _Summary(StrictModel):
    complete_stream: StrictBool
    exit_code: StrictInt
    build_target_configuration_count: StrictInt
    failed_build_target_configuration_count: StrictInt
    build_target_results: dict[str, StrictBool]
    test_target_count: StrictInt
    test_targets: dict[str, str]


class _Configuration(StrictModel):
    id: Digest


class _Target(StrictModel):
    label: str
    configuration: _Configuration


class _BuildID(StrictModel):
    targetCompleted: _Target


class _Scope(StrictModel):
    selected: list[str]
    patterns: list[str]
    build_configurations: dict[str, list[str]]
    production_omission_authorized: StrictBool
    requires_independent_full_control: StrictBool


def read_execution_config(path: Path) -> ExecutionConfig:
    return ExecutionConfig.model_validate(
        json.loads(
            read_bounded(path, MAX_MANIFEST_BYTES), object_pairs_hook=unique_object
        )
    )


def reconcile_execution(
    raw: bytes,
    code: int,
    profile: Profile,
    patterns: list[str],
    expected: NativeInventory | None,
) -> tuple[dict[str, object], list[str]]:
    """Require complete events, exact command profile and the executed target scope.

    Full fallback uses the native wildcard, which can legitimately discover new
    tests after a build-definition change. Only a subset is bound to the map's
    exact test and build-only configuration inventory.
    """
    summary = _Summary.model_validate(summarize_bytes(raw))
    if summary.exit_code != code:
        raise QueryError("native process and evidence disagree")
    observed_patterns = []
    for line in raw.splitlines():
        event = json.loads(line, object_pairs_hook=unique_object)
        if "started" in event:
            start = event["started"]
            options = start.get("optionsDescription")
            workspace = start.get("workspaceDirectory")
            if (
                start.get("buildToolVersion") != profile.bazel_version
                or not isinstance(options, str)
                or sha256(options.encode()) != profile.options_digest
                or not isinstance(workspace, str)
                or not workspace
                or start.get("workingDirectory") != workspace
            ):
                raise QueryError("executed native profile differs")
        if "pattern" in event["id"]:
            observed_patterns.append(event["id"]["pattern"])
    if observed_patterns != [{"pattern": patterns}]:
        raise QueryError("native target patterns differ from the plan")
    builds: dict[str, dict[str, bool]] = {}
    for key, success in summary.build_target_results.items():
        target = _BuildID.model_validate_json(key).targetCompleted
        configurations = builds.setdefault(target.label, {})
        if target.configuration.id in configurations:
            raise QueryError("duplicate native build configuration")
        configurations[target.configuration.id] = success
    failures = sorted(
        name for name, values in builds.items() if not any(values.values())
    )
    if expected is not None:
        actual = {name: tuple(sorted(values)) for name, values in builds.items()}
        if actual != expected.build_configurations:
            raise QueryError("native test or build-only configuration scope differs")
        accounted = set(summary.test_targets)
        if code == 1:
            accounted |= set(failures) & set(expected.tests)
        if accounted != set(expected.tests):
            raise QueryError("missing or unexpected native test outcome")
    if any(
        name not in builds
        or (not all(builds[name].values()) and status != "FAILED_TO_BUILD")
        for name, status in summary.test_targets.items()
    ):
        raise QueryError("test outcome contradicts native build")
    if code == 0 and set(summary.test_targets.values()) != {"PASSED"}:
        raise QueryError("nonpassing or flaky native outcome")
    return summary.model_dump(), failures


def execute(
    repo: Path,
    base: str,
    head: str,
    config: ExecutionConfig,
    output: Path,
    *,
    bundle_path: Path | None = None,
    expected_digest: str | None = None,
    must_run: tuple[str, ...] = (),
    force_full: bool = False,
) -> dict[str, object]:
    from .commands import revision_tree, verify_checkout

    started = time.monotonic()
    tree = verify_checkout(repo, head)
    if output.is_relative_to(repo) or (
        bundle_path is not None
        and (output.is_relative_to(bundle_path) or bundle_path.is_relative_to(output))
    ):
        raise QueryError("execution output overlaps inputs")
    output.mkdir(mode=0o700, exist_ok=False)
    plan: dict[str, object] = {
        "schema_version": "smartci.bazel-bundle-plan.v1",
        "mode": "full",
        "patterns": ["..."],
        "fallback": [
            "FORCE_FULL"
            if force_full
            else "MISSING_INVALID_OR_INCOMPATIBLE_NATIVE_EVIDENCE"
        ],
        "comparison": {"base": base, "head": head},
        "production_omission_authorized": False,
        "requires_independent_full_control": False,
    }
    expected = None
    patterns = ["..."]
    if not force_full:
        try:
            if bundle_path is None or expected_digest is None:
                raise QueryError("missing map")
            bundle = load(bundle_path, expected_digest, config.profile)
            if (
                parse_tree(revision_tree(repo, bundle.manifest.anchor_commit))
                != bundle.anchor
            ):
                raise QueryError("map source tree differs")
            proposed = bundle.plan(
                parse_tree(revision_tree(repo, base)),
                parse_tree(tree),
                must_run=must_run,
                execution_mode="selective",
            )
            if proposed["mode"] == "subset":
                scope = _Scope.model_validate(
                    {key: proposed[key] for key in _Scope.model_fields}
                )
                if (
                    not scope.production_omission_authorized
                    or scope.requires_independent_full_control
                ):
                    raise QueryError("subset execution is not authorized")
                expected = NativeInventory(
                    {
                        name: tuple(ids)
                        for name, ids in scope.build_configurations.items()
                    },
                    tuple(scope.selected),
                )
                patterns = scope.patterns
            proposed["comparison"] = {"base": base, "head": head}
            plan = proposed
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
        ):
            # A failure to prove a subset must not suppress the native command.
            expected, patterns = None, ["..."]
    plan.pop("digest", None)
    plan["digest"] = sha256(canonical(plan))
    (output / "plan.json").write_bytes(canonical(plan))
    capture = output / "capture"
    capture.mkdir(mode=0o700)
    (capture / "targets.txt").write_text("\n".join(patterns) + "\n")
    subset = expected is not None
    planning_seconds = time.monotonic() - started
    report: dict[str, object] = {
        "schema_version": "smartci.bazel-execution.v1",
        "base": base,
        "head": head,
        "mode": plan["mode"],
        "plan_digest": plan["digest"],
        "config_digest": sha256(canonical(config.model_dump())),
        "planning_seconds": planning_seconds,
        "status": "failed",
        "exit_code": None,
        "error": None,
        "model_calls": 0,
    }
    print(
        f"Native PR execution: mode={plan['mode']}; fallback={plan['fallback']}",
        flush=True,
    )
    command_started = time.monotonic()
    stage = "NATIVE_EXECUTION"
    try:
        # Recheck immediately before executing repository build logic.
        verify_checkout(repo, head)
        code = run_command(config.subset if subset else config.full, repo, capture)
        report["exit_code"] = code
        report["command_seconds"] = time.monotonic() - command_started
        stage = "NATIVE_VALIDATION"
        raw = read_bounded(capture / "native.bep.json", LIMITS["native.bep.json"])
        profile = (
            config.profile.model_copy(
                update={"options_digest": config.subset_options_digest}
            )
            if subset
            else config.profile
        )
        summary, failures = reconcile_execution(raw, code, profile, patterns, expected)
        if verify_checkout(repo, head) != tree:
            raise QueryError("source changed during native execution")
        report.update(
            status="passed" if code == 0 else "failed",
            bazel=summary,
            failed_build_targets=failures,
            evidence_digest=sha256(raw),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        subprocess.SubprocessError,
    ):
        report["error"] = stage + "_FAILED"
    report["process_seconds"] = time.monotonic() - started
    (output / "execution.json").write_bytes(canonical(report))
    return report
