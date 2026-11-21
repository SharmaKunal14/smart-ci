"""Bounded local adapters for pytest cases, Vitest files and Maven classes."""

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from smartci.contracts import TestUnit
from smartci.selection import digest

Kind = Literal["pytest", "vitest", "maven"]
Outcome = Literal["passed", "failed", "skipped"]


class AdapterError(ValueError):
    """Discovery, invocation or result reconciliation could not be completed."""


@dataclass(frozen=True)
class Unit:
    id: str
    target: str
    path: str


@dataclass(frozen=True)
class RunResult:
    status: Literal["passed", "failed", "incomplete"]
    expected: list[str]
    observed: dict[str, Outcome]
    returncode: int
    duration: float


def read_bounded(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AdapterError("report too large")
    return data


def invoke(
    args: list[str], cwd: Path, timeout: int = 120, env: dict[str, str] | None = None
) -> int:
    # Runner output can contain secrets; do not relay or persist it as operator logs.
    try:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The process can exit between the timeout and kill.
            process.wait()
            raise AdapterError("runner timed out") from exc
    except OSError as exc:
        raise AdapterError("runner unavailable") from exc


class PyReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    collected: list[str]
    results: dict[str, Outcome]
    exit: int
    plugins: list[str] = []
    skip_reasons: dict[str, str] = {}


class Assertion(BaseModel):
    status: str


class VitestFile(BaseModel):
    name: str
    assertionResults: list[Assertion]


class VitestReport(BaseModel):
    testResults: list[VitestFile]


class ListedTest(BaseModel):
    file: str


@dataclass
class Runner:
    kind: Kind
    root: Path
    repository: str
    python: str | None = None
    native_pytest: bool = False
    pytest_granularity: Literal["case", "file"] = "case"
    pytest_args: tuple[str, ...] = ()
    pytest_cases: tuple[str, ...] = field(default=(), init=False)
    pytest_plugins: tuple[str, ...] = field(default=(), init=False)
    native_results: dict[str, Outcome] = field(default_factory=dict, init=False)

    def relative(self, path: Path) -> str:
        try:
            relative = (
                path.resolve(strict=True).relative_to(self.root.resolve()).as_posix()
            )
            TestUnit.relative_path(relative)
            return relative
        except (OSError, ValueError) as exc:
            raise AdapterError("test path outside runner root") from exc

    def unit(self, target: str, path: str) -> Unit:
        return Unit(f"{self.repository}/{self.kind}:{digest(target)}", target, path)

    def python_command(self, report: Path) -> tuple[list[str], dict[str, str]]:
        env = dict(os.environ)
        env["SMARTCI_REPORT"] = str(report)
        options = []
        if self.native_pytest:
            # A fresh cache prevents stale timestamp-based bytecode across Git revisions.
            env["PYTHONPYCACHEPREFIX"] = str(report.parent / "pycache")
        else:
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            env["PYTEST_ADDOPTS"] = ""
            env.pop("PYTEST_PLUGINS", None)
            options = ["-o", "addopts="]
        return [
            self.python or sys.executable,
            "-m",
            "pytest",
            "-p",
            "smartci.adapters.pytest_plugin",
            *options,
            *self.pytest_args,
        ], env

    def vitest_command(self) -> list[str]:
        if (
            any(self.root.glob("vitest.config.*"))
            or any(self.root.glob("vite.config.*"))
            or any(self.root.glob("vitest.workspace.*"))
        ):
            raise AdapterError("custom Vitest configuration is not supported yet")
        executable = self.root / "node_modules/vitest/vitest.mjs"
        if not executable.is_file():
            raise AdapterError("install pinned Vitest dependencies first")
        return ["node", str(executable.resolve())]

    def discover(self) -> list[Unit]:
        try:
            with tempfile.TemporaryDirectory(prefix="smartci-discovery-") as temp:
                report = Path(temp) / "discovery.json"
                if self.kind == "pytest":
                    command, env = self.python_command(report)
                    if invoke([*command, "--collect-only", "-q"], self.root, env=env):
                        raise AdapterError("pytest discovery failed")
                    data = PyReport.model_validate_json(
                        read_bounded(report, 32 * 1024 * 1024)
                    )
                    if (
                        data.exit != 0
                        or len(data.collected) > 100_000
                        or len(set(data.collected)) != len(data.collected)
                    ):
                        raise AdapterError("invalid pytest collection")
                    self.pytest_cases = tuple(sorted(data.collected))
                    self.pytest_plugins = tuple(sorted(data.plugins))
                    targets = (
                        sorted({t.split("::")[0] for t in data.collected})
                        if self.pytest_granularity == "file"
                        else data.collected
                    )
                    units = [
                        self.unit(t, self.relative(self.root / t.split("::")[0]))
                        for t in targets
                    ]
                elif self.kind == "vitest":
                    if invoke(
                        [*self.vitest_command(), "list", f"--json={report}"], self.root
                    ):
                        raise AdapterError("Vitest discovery failed")
                    entries = TypeAdapter(list[ListedTest]).validate_json(
                        read_bounded(report)
                    )
                    files = sorted({self.relative(Path(e.file)) for e in entries})
                    units = [self.unit(f, f) for f in files]
                else:
                    units = self.discover_java()
            if (
                not units
                or len(units) > 100_000
                or len({u.id for u in units}) != len(units)
            ):
                raise AdapterError("empty, excessive or duplicate discovery")
            return sorted(units, key=lambda u: u.id)
        except (OSError, ValueError, ET.ParseError) as exc:
            raise AdapterError("discovery incomplete") from exc

    def discover_java(self) -> list[Unit]:
        # Supported profile: single module, ordinary top-level *Test.java classes.
        self.relative(self.root / "pom.xml")
        pom = read_bounded(self.root / "pom.xml")
        if b"\x00" in pom or b"<!DOCTYPE" in pom or b"<!ENTITY" in pom:
            raise AdapterError("XML declarations forbidden")
        tree = ET.fromstring(pom)
        unsupported = {
            "modules",
            "profiles",
            "includes",
            "excludes",
            "suiteXmlFiles",
            "groups",
            "excludedGroups",
            "testSourceDirectory",
            "dependenciesToScan",
        }
        if any(e.tag.split("}")[-1] in unsupported for e in tree.iter()):
            raise AdapterError("unsupported Maven discovery configuration")
        units = []
        for path in sorted((self.root / "src/test/java").rglob("*.java")):
            relative = self.relative(path)
            source = read_bounded(path).decode()
            if "@Nested" in source or "@TestFactory" in source:
                raise AdapterError("unsupported dynamic/nested JUnit discovery")
            if not path.stem.endswith("Test"):
                if "@Test" in source or "@ParameterizedTest" in source:
                    raise AdapterError("unsupported test class convention")
                continue
            package = re.search(r"^package ([A-Za-z_][\w.]*)\s*;", source, re.MULTILINE)
            if not package or not re.fullmatch(r"[A-Za-z_]\w*", path.stem):
                raise AdapterError("unsupported Java class")
            target = f"{package[1]}.{path.stem}"
            units.append(self.unit(target, relative))
        return units

    def run(self, units: list[Unit], selected: set[str] | None = None) -> RunResult:
        self.native_results = {}
        chosen = units if selected is None else [u for u in units if u.id in selected]
        if not chosen or (selected is not None and selected != {u.id for u in chosen}):
            raise AdapterError("unknown or empty selection")
        start = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="smartci-results-") as temp:
                report = Path(temp) / "results.json"
                targets = [] if selected is None else [u.target for u in chosen]
                if self.kind == "pytest":
                    command, env = self.python_command(report)
                    code = invoke([*command, "-q", "--", *targets], self.root, env=env)
                    native = PyReport.model_validate_json(
                        read_bounded(report, 32 * 1024 * 1024)
                    )
                    self.native_results = native.results
                    observed = self.pytest_results(native, chosen, code)
                elif self.kind == "vitest":
                    env = dict(os.environ, SMARTCI_PYTHON=sys.executable)
                    code = invoke(
                        [
                            *self.vitest_command(),
                            "run",
                            "--allowOnly=false",
                            "--retry=0",
                            "--reporter=json",
                            f"--outputFile={report}",
                            *[str(self.root / target) for target in targets],
                        ],
                        self.root,
                        env=env,
                    )
                    observed = self.vitest_results(report)
                else:
                    command = [
                        "mvn",
                        "-B",
                        "-q",
                        "-Dmaven.repo.local="
                        + str(
                            Path(
                                os.environ.get("SMARTCI_MAVEN_CACHE", "/tmp/smartci-m2")
                            ).resolve()
                        ),
                        "-DfailIfNoTests=true",
                        "-Dsurefire.failIfNoSpecifiedTests=true",
                        f"-Dsmartci.reports={temp}",
                        "-DskipTests=false",
                        "-Dmaven.test.skip=false",
                        "-Dmaven.test.failure.ignore=false",
                        "-Dsurefire.rerunFailingTestsCount=0",
                    ]
                    if targets:
                        command.append("-Dtest=" + ",".join(targets))
                    code = invoke([*command, "test"], self.root, timeout=180)
                    observed = self.java_results(Path(temp))
                return reconcile(chosen, observed, code, time.monotonic() - start)
        except (OSError, ValueError, KeyError, ET.ParseError):
            return RunResult(
                "incomplete",
                sorted(u.id for u in chosen),
                {},
                -1,
                time.monotonic() - start,
            )

    def pytest_results(
        self, native: PyReport, chosen: list[Unit], code: int
    ) -> dict[str, Outcome]:
        targets = {u.target for u in chosen}
        expected = (
            {t for t in self.pytest_cases if t.split("::")[0] in targets}
            if self.pytest_granularity == "file"
            else targets
        )
        if (
            not expected
            or native.exit != code
            or len(native.collected) != len(expected)
            or set(native.collected) != expected
            or set(native.results) != expected
            or tuple(sorted(native.plugins)) != self.pytest_plugins
        ):
            return {}
        if self.pytest_granularity == "case":
            return native.results
        grouped: dict[str, set[Outcome]] = {t: set() for t in targets}
        for case, outcome in native.results.items():
            grouped[case.split("::")[0]].add(outcome)
        return {
            target: "failed"
            if "failed" in outcomes
            else "passed"
            if outcomes == {"passed"}
            else "skipped"
            for target, outcomes in grouped.items()
        }

    def vitest_results(self, path: Path) -> dict[str, Outcome]:
        report = VitestReport.model_validate_json(read_bounded(path))
        result: dict[str, Outcome] = {}
        for entry in report.testResults:
            name = self.relative(Path(entry.name))
            if name in result or not entry.assertionResults:
                raise AdapterError("duplicate or empty Vitest file result")
            statuses = {a.status for a in entry.assertionResults}
            result[name] = (
                "failed"
                if "failed" in statuses
                else "passed"
                if statuses == {"passed"}
                else "skipped"
            )
        return result

    def java_results(self, directory: Path) -> dict[str, Outcome]:
        result: dict[str, Outcome] = {}
        for path in directory.glob("TEST-*.xml"):
            raw = read_bounded(path)
            if b"\x00" in raw or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
                raise AdapterError("XML declarations forbidden")
            tree = ET.fromstring(raw)
            name = tree.attrib["name"]
            cases = tree.findall("testcase")
            if tree.tag != "testsuite" or int(tree.attrib.get("tests", "-1")) != len(
                cases
            ):
                raise AdapterError("inconsistent Java report")
            if name in result or not cases:
                raise AdapterError("empty or duplicate Java report")
            result[name] = (
                "failed"
                if any(
                    c.find("failure") is not None or c.find("error") is not None
                    for c in cases
                )
                else "skipped"
                if any(c.find("skipped") is not None for c in cases)
                else "passed"
            )
        return result


def reconcile(
    units: list[Unit], observed: dict[str, Outcome], code: int, duration: float
) -> RunResult:
    mapping = {u.target: u.id for u in units}
    normalized = {
        mapping[t]: outcome for t, outcome in observed.items() if t in mapping
    }
    if set(mapping) != set(observed) or "skipped" in observed.values():
        status: Literal["passed", "failed", "incomplete"] = "incomplete"
    elif "failed" in observed.values():
        status = "failed"
    elif code != 0:
        status = "incomplete"
    else:
        status = "passed"
    return RunResult(status, sorted(mapping.values()), normalized, code, duration)
