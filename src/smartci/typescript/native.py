"""Bounded native Vitest invocation; no npm scripts or model/cloud clients."""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from smartci.adapters.runners import invoke, read_bounded
from smartci.contracts import TestUnit
from smartci.selection import digest

from .models import ListedFile, NativeProject, NativeReport, NativeResult


class NativeVitest:
    def __init__(
        self,
        root: Path,
        node: str | None = None,
        offline: bool = False,
        project: NativeProject | None = None,
        pnpm: str | None = None,
        dependency_store: Path | None = None,
        dependency_cache: Path | None = None,
    ):
        self.root = root.resolve(strict=True)
        self.project = project
        self.pnpm = pnpm
        self.dependency_store = dependency_store
        self.dependency_cache = dependency_cache
        self.cwd = self.root
        if project:
            self.cwd = (self.root / project.directory).resolve(strict=True)
            configuration = (self.root / project.configuration).resolve(strict=True)
            if not self.cwd.is_relative_to(
                self.root
            ) or not configuration.is_relative_to(self.root):
                raise ValueError("native project escaped repository")
        executable = shutil.which(node or "node")
        if executable is None:
            raise ValueError("Node unavailable")
        self.node = executable
        self.prefix: list[str] = []
        if offline:
            sandbox = shutil.which("sandbox-exec")
            if sandbox is None:
                raise ValueError("macOS sandbox-exec required for --offline")
            self.prefix = [
                sandbox,
                "-p",
                "(version 1)(allow default)(deny network-outbound)",
            ]

    def invoke(self, args: list[str], timeout: int = 180) -> int:
        # Never inherit AWS, model-provider, GitHub credentials, NODE_OPTIONS or
        # developer home configuration. This is hygiene, not a code sandbox.
        with tempfile.TemporaryDirectory(prefix="smartci-home-") as home:
            project = getattr(self, "project", None)
            env = {
                "PATH": os.pathsep.join(
                    [str(Path(self.node).parent), "/usr/bin", "/bin"]
                ),
                "HOME": home,
                "TMPDIR": tempfile.gettempdir(),
                "CI": "true",
                "LANG": "C.UTF-8",
                "TZ": project.timezone if project else "UTC",
            }
            return invoke(
                [*self.prefix, self.node, *args],
                getattr(self, "cwd", self.root),
                timeout,
                env,
            )

    def vitest(self, args: list[str]) -> int:
        project = getattr(self, "project", None)
        options = (
            [
                "--config",
                str(self.root / project.configuration),
                "--project",
                project.project,
            ]
            if project
            else ["--config", "vitest.config.ts", "--maxWorkers=2"]
        )
        return self.invoke(
            [
                str(self.root / "node_modules/vitest/vitest.mjs"),
                *args,
                *options,
                "--allowOnly=false",
                "--passWithNoTests=false",
            ],
            timeout=600,
        )

    def relative(self, filename: str) -> str:
        path = Path(filename)
        if not path.is_absolute():
            raise ValueError("absolute native filename required")
        relative = path.resolve(strict=True).relative_to(self.root).as_posix()
        TestUnit.relative_path(relative)
        return relative

    def collect(self) -> list[str]:
        # File selection needs Vitest's resolved file inventory, not execution of
        # every test module to enumerate cases. Tests run only in selected files.
        with tempfile.TemporaryDirectory(prefix="smartci-list-") as temporary:
            report = Path(temporary) / "files.json"
            if self.vitest(["list", "--filesOnly", f"--json={report}"]) != 0:
                raise ValueError("native file discovery failed")
            files = TypeAdapter(list[ListedFile]).validate_json(read_bounded(report))
        project = getattr(self, "project", None)
        if project and any(file.projectName != project.project for file in files):
            raise ValueError("unexpected native project")
        if not project and any(file.projectName is not None for file in files):
            raise ValueError("Vitest workspaces not supported")
        paths = [self.relative(file.file) for file in files]
        if not paths or len(paths) > 100_000 or len(set(paths)) != len(paths):
            raise ValueError("empty, duplicate or oversized file inventory")
        return sorted(paths)

    def run(self, expected: list[str] | None, subset: bool) -> NativeResult:
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="smartci-run-") as temporary:
            report = Path(temporary) / "result.json"
            filters = (
                [str(self.root / p) for p in sorted(expected or {})] if subset else []
            )
            if subset and not filters:
                raise ValueError("empty subset forbidden")
            code = -1
            try:
                code = self.vitest(
                    ["run", *filters, "--reporter=json", f"--outputFile={report}"]
                )
                native = NativeReport.model_validate_json(read_bounded(report))
                return reconcile(native, code, expected, self, time.monotonic() - start)
            except (OSError, ValueError):
                return NativeResult(
                    status="incomplete",
                    files=[],
                    cases=0,
                    failed=0,
                    skipped=0,
                    returncode=code,
                    duration_seconds=time.monotonic() - start,
                )


def reconcile(
    report: NativeReport,
    code: int,
    expected: list[str] | None,
    runner: NativeVitest,
    duration: float,
) -> NativeResult:
    observed: dict[str, list[str]] = {}
    failed = skipped = count = 0
    failed_cases = []
    skipped_cases: set[str] = set()
    reviewed: set[str] = set()
    valid = True
    project = getattr(runner, "project", None)
    if project:
        for rule in project.reviewed_skips:
            try:
                source = (runner.root / rule.path).resolve(strict=True)
                if not source.is_relative_to(runner.root):
                    raise ValueError("skip source escaped repository")
                if (
                    hashlib.sha256(read_bounded(source)).hexdigest()
                    != rule.source_digest
                ):
                    raise ValueError("skip review is stale")
            except (OSError, ValueError):
                valid = False
            if expected is None or rule.path in expected:
                reviewed.add(rule.case)
    for result in report.testResults:
        path = runner.relative(result.name)
        if path in observed or not result.assertionResults:
            valid = False
        observed[path] = []
        for case in result.assertionResults:
            observed[path].append(" > ".join([*case.ancestorTitles, case.title]))
            count += 1
            failed += case.status == "failed"
            if case.status == "failed":
                failed_cases.append(digest([path, case.ancestorTitles, case.title]))
            skipped += case.status not in {"passed", "failed"}
            if case.status == "skipped":
                skipped_cases.add(digest([path, case.ancestorTitles, case.title]))
    if expected is not None and set(expected) != set(observed):
        valid = False
    valid = (
        valid
        and bool(count)
        and skipped == len(skipped_cases)
        and skipped_cases == reviewed
        and code in (0, 1)
    )
    status: Literal["passed", "failed", "incomplete"]
    if failed and valid:
        status = "failed"
    elif valid and code == 0 and report.success:
        status = "passed"
    else:
        status = "incomplete"
    return NativeResult(
        status=status,
        files=sorted(observed),
        cases=count,
        failed=failed,
        failed_cases=sorted(failed_cases),
        skipped=skipped,
        returncode=code,
        duration_seconds=duration,
        reviewed_skips=sorted(reviewed),
    )
