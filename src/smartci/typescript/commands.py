"""Reconstruct both revisions before planning; map files are audit outputs only."""

import argparse
import html
import json
import tempfile
import time
from pathlib import Path

from smartci.adapters.runners import invoke, read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.discovery.commands import write_json
from smartci.git_changes import changes_from_git, git
from smartci.reports import atomic_write, markdown
from smartci.selection import Report, SelectionPolicy, fallback, finish, select

from .collector import collect, test_id
from .models import NativeResult, TypeScriptConfig, TypeScriptSnapshot
from .native import NativeVitest
from .workspace import check_environment


def progress(message: str) -> None:
    print(f"smartci: {message}", flush=True)


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("typescript", help="compiler-backed native Vitest planning")
    actions = parser.add_subparsers(dest="ts_action", required=True)
    for name in ("scan", "run"):
        action = actions.add_parser(name)
        action.add_argument("--repo", required=True, type=Path)
        action.add_argument("--config", required=True, type=Path)
        action.add_argument("--output", required=True, type=Path)
        action.add_argument("--node")
        action.add_argument(
            "--pnpm", help="absolute path to pnpm's JavaScript entry point"
        )
        action.add_argument(
            "--dependency-store", type=Path, help="populated pnpm content store"
        )
        action.add_argument(
            "--dependency-cache",
            type=Path,
            help="populated pnpm registry metadata cache",
        )
        action.add_argument(
            "--offline",
            action="store_true",
            help="deny outbound network using macOS sandbox-exec",
        )
        if name == "scan":
            action.add_argument("--run-full", action="store_true")
        else:
            action.add_argument(
                "--base",
                required=True,
                help="full Git commit ID; merge base is reconstructed",
            )
            action.add_argument("--shadow", action="store_true")


def rebuild_base(
    runner: NativeVitest, config: TypeScriptConfig, base: str
) -> TypeScriptSnapshot:
    # Every workspace manifest must match before sharing external dependencies.
    head = current_clean_head(runner.root)
    if head is None:
        raise ValueError("dirty head during reconstruction")
    check_environment(
        runner.root,
        base,
        head,
        config.native_project.lockfile
        if config.native_project
        else "package-lock.json",
    )
    with tempfile.TemporaryDirectory(prefix="smartci-base-") as temporary:
        root = Path(temporary) / "repository"
        if (
            invoke(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "clone",
                    "--shared",
                    "--no-checkout",
                    "--",
                    str(runner.root),
                    str(root),
                ],
                runner.root,
            )
            != 0
        ):
            raise ValueError("cannot reconstruct base")
        git(root, "-c", "core.hooksPath=/dev/null", "checkout", "--detach", base)
        if (root / "node_modules").exists():
            raise ValueError("tracked dependencies unsupported")
        with (root / ".git/info/exclude").open("a") as ignore:
            ignore.write("\n/node_modules\n")
        if not config.native_project:
            (root / "node_modules").symlink_to(
                runner.root / "node_modules", target_is_directory=True
            )
        base_runner = NativeVitest(
            root,
            runner.node,
            offline=bool(runner.prefix),
            project=config.native_project,
            pnpm=runner.pnpm,
            dependency_store=runner.dependency_store,
            dependency_cache=runner.dependency_cache,
        )
        if config.native_project:
            # Reinstall offline into a private virtual store. Sharing head's
            # node_modules can silently resolve old imports to NEW workspace code.
            if (
                not runner.pnpm
                or not runner.dependency_store
                or not runner.dependency_cache
            ):
                raise ValueError("pnpm and populated dependency store/cache required")
            if any(root.rglob(".pnpmfile.*")) or any(
                b"pnpmfile" in read_bounded(root / p).lower()
                for p in (".npmrc", "pnpm-workspace.yaml", "package.json")
                if (root / p).is_file()
            ):
                raise ValueError("pnpm hooks require a separate environment adapter")
            if (
                base_runner.invoke(
                    [
                        str(Path(runner.pnpm).resolve(strict=True)),
                        "--dir",
                        str(root),
                        "install",
                        "--offline",
                        "--frozen-lockfile",
                        "--ignore-scripts",
                        "--ignore-pnpmfile",
                        "--store-dir",
                        str(runner.dependency_store.resolve(strict=True)),
                        "--cache-dir",
                        str(runner.dependency_cache.resolve(strict=True)),
                    ],
                    timeout=300,
                )
                != 0
            ):
                raise ValueError("offline base dependency reconstruction failed")
        return collect(base_runner, config)


def planning(
    runner: NativeVitest,
    config: TypeScriptConfig,
    base: str,
    shadow: bool,
    output: Path,
) -> tuple[Report, TypeScriptSnapshot | None]:
    head: TypeScriptSnapshot | None = None
    try:
        progress("discovering PR tests and building the head dependency map")
        head = collect(runner, config)
        write_json(output / "head-map.json", head.model_dump())
        changes = changes_from_git(
            runner.root, base, head.graph.commit, config.repository
        )
        progress(
            "rebuilding the merge-base map from source; no saved baseline required"
        )
        before = rebuild_base(runner, config, changes.base)
        write_json(output / "base-map.json", before.model_dump())
        if before.provenance != head.provenance:
            return fallback("ENVIRONMENT_MISMATCH", head.inventory), head
        # A changed source outside the enrolled compiler projects is unsupported,
        # even though tracked non-code resources have conservative graph owners.
        analyzed = set(before.analyzed) | set(head.analyzed)
        unsupported = [
            p
            for p in changes.paths
            if p.endswith(
                (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")
            )
            and p not in analyzed
        ]
        if unsupported:
            return fallback("SOURCE_OUTSIDE_SUPPORTED_PROJECTS", head.inventory), head
        policy = SelectionPolicy(
            schema_version="1",
            repository=config.repository,
            mode="shadow" if shadow else "selective",
            must_run=[test_id(p) for p in config.must_run],
            full_paths=[
                "**/tsconfig*",
                "tsconfig*",
                "**/vitest.config.*",
                "vitest.config.*",
                "**/vite.config.*",
                "vite.config.*",
                "vitest.workspace.*",
                "pnpm-workspace.yaml",
                "**/mise.toml",
                "mise.toml",
                "**/.npmrc",
                ".npmrc",
                *config.full_paths,
            ],
        )
        decision = select(changes, head.inventory, before.graph, head.graph, policy)
        decision.warnings = sorted(
            {*decision.warnings, *head.warnings, *before.warnings}
        )
        return finish(decision), head
    except (OSError, ValueError, RecursionError):
        progress(
            "analysis unavailable: falling back to the independent full Vitest suite"
        )
        return fallback(
            "MAP_REBUILD_OR_DISCOVERY_FAILED", head.inventory if head else None
        ), head


def execute(
    runner: NativeVitest, report: Report, snapshot: TypeScriptSnapshot | None
) -> tuple[list[NativeResult], str, list[str]]:
    expected = snapshot.files if snapshot else None
    mode = report.execution
    reasons = list(report.fallback)
    if snapshot and current_clean_head(runner.root) != snapshot.graph.commit:
        mode = "full"
        reasons.append("WORKSPACE_CHANGED_BEFORE_RUN")
        expected = None
    selected = (
        [p for p in expected if test_id(p) in report.selected]
        if mode == "subset" and expected
        else expected
    )
    progress(
        f"running {len(selected) if selected else 'all'} Vitest files; execution={mode}"
    )
    attempts = [runner.run(selected, subset=mode == "subset")]
    if mode == "subset" and attempts[0].status == "incomplete":
        reasons.append("INCOMPLETE_SUBSET_RESULTS")
        mode = "full"
        progress("subset result could not be reconciled; running the full suite")
        attempts.append(runner.run(expected, subset=False))
    if snapshot and current_clean_head(runner.root) != snapshot.graph.commit:
        reasons.append("WORKSPACE_CHANGED_DURING_RUN")
        attempts[-1].status = "incomplete"
    return attempts, mode, reasons


def command(args: argparse.Namespace) -> int:
    start = time.monotonic()
    try:
        root = args.repo.resolve(strict=True)
        output = args.output.resolve()
        if (
            output.exists()
            or output.is_relative_to(root)
            or args.config.resolve().is_relative_to(output)
        ):
            raise ValueError("new output directory outside target checkout required")
        config = TypeScriptConfig.model_validate_json(read_bounded(args.config))
        runner = NativeVitest(
            root,
            args.node,
            args.offline,
            project=config.native_project,
            pnpm=getattr(args, "pnpm", None),
            dependency_store=getattr(args, "dependency_store", None),
            dependency_cache=getattr(args, "dependency_cache", None),
        )
        output.mkdir(parents=True)
        snapshot: TypeScriptSnapshot | None
        if args.ts_action == "scan":
            progress("scanning tracked code and collecting native Vitest tests twice")
            snapshot = collect(runner, config)
            write_json(output / "head-map.json", snapshot.model_dump())
            progress(
                f"discovered {len(snapshot.files)} test files; graph gaps={snapshot.gaps}"
            )
            if not args.run_full:
                return 0 if snapshot.graph.complete else 2
            report = fallback("INITIAL_FULL_VERIFICATION", snapshot.inventory)
        else:
            report, snapshot = planning(runner, config, args.base, args.shadow, output)
        write_json(output / "selection.json", report.model_dump())
        readable = ""
        if snapshot:
            selected_paths = sorted(
                t.path for t in snapshot.inventory.tests if t.id in report.selected
            )
            readable = "\n\n## Selected Vitest files\n\n<pre>"
            readable += html.escape(json.dumps(selected_paths, indent=2)) + "</pre>"
            readable += (
                f"\n\n{len(selected_paths)}/{len(snapshot.files)} files proposed. "
            )
            readable += "Selection is conditional on the supported static-analysis profile, not a safety guarantee.\n"
        atomic_write(output / "audit.md", markdown(report) + readable)
        planning_seconds = time.monotonic() - start
        attempts, mode, reasons = execute(runner, report, snapshot)
        status = (
            "failed"
            if any(a.failed or a.status == "failed" for a in attempts)
            else attempts[-1].status
        )
        result = {
            "schema_version": "1",
            "repository": config.repository,
            "status": status,
            "execution": mode,
            "fallback": reasons,
            "decision_digest": report.digest,
            "planning_seconds": planning_seconds,
            "total_seconds": time.monotonic() - start,
            "selected_files": sorted(
                t.path for t in snapshot.inventory.tests if t.id in report.selected
            )
            if snapshot
            else [],
            "attempts": [a.model_dump() for a in attempts],
        }
        write_json(output / "run.json", result)
        progress(
            f"{status}; executed {len(attempts[-1].files)} files, {attempts[-1].cases} cases; fallback={reasons}"
        )
        return {"passed": 0, "failed": 1, "incomplete": 2}[status]
    except (OSError, ValueError, RecursionError):
        print(
            json.dumps(
                {"status": "incomplete", "code": "TYPESCRIPT_ADAPTER_OR_OUTPUT_ERROR"}
            ),
            flush=True,
        )
        return 2
