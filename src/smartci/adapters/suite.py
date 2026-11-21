"""Trusted local suite configuration and conservative execution orchestration."""

import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smartci.contracts import Contract, Identifier, Inventory, TestUnit
from smartci.selection import Report, digest

from .results import RunReport
from .runners import AdapterError, Kind, Runner, Unit, read_bounded


class SuiteEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: Identifier
    runner: Kind
    path: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return TestUnit.relative_path(value)


class SuiteConfig(Contract):
    suites: list[SuiteEntry] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        for attr in ("name", "path"):
            if len({getattr(s, attr) for s in self.suites}) != len(self.suites):
                raise ValueError("duplicate suite")
        return self


@dataclass
class Discovered:
    config: SuiteConfig
    root: Path
    inventory: Inventory
    runners: list[tuple[SuiteEntry, Runner, list[Unit]]]


def discover(config_path: Path) -> Discovered:
    config = SuiteConfig.model_validate_json(read_bounded(config_path))
    root = config_path.resolve().parent
    tests: list[TestUnit] = []
    runners = []
    fingerprints: dict[str, str] = {}
    for entry in config.suites:
        path = (root / entry.path).resolve(strict=True)
        if not path.is_relative_to(root):
            raise AdapterError("suite escapes configuration root")
        runner = Runner(entry.runner, path, f"{config.repository}/{entry.name}")
        units = runner.discover()
        runners.append((entry, runner, units))
        granularities: dict[Kind, Literal["case", "file", "class"]] = {
            "pytest": "case",
            "vitest": "file",
            "maven": "class",
        }
        granularity = granularities[entry.runner]
        tests.extend(
            TestUnit(
                id=u.id,
                runner=entry.runner,
                granularity=granularity,
                path=f"{entry.path}/{u.path}",
            )
            for u in units
        )
        for filename in ("package-lock.json", "pom.xml", "pytest.ini"):
            source = path / filename
            if source.is_file():
                runner.relative(source)
                fingerprints[f"{entry.path}/{filename}"] = digest(
                    read_bounded(source).hex()
                )
    environment = digest(
        {
            "python": platform.python_version(),
            "platform": platform.system(),
            "config": config.model_dump(),
            "dependencies": fingerprints,
        }
    )
    inventory = Inventory(
        schema_version="1",
        repository=config.repository,
        complete=True,
        environment=environment,
        tests=sorted(tests, key=lambda t: t.id),
    )
    return Discovered(config, root, inventory, runners)


def current_clean_head(root: Path) -> str | None:
    try:
        head = (
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            .stdout.decode()
            .strip()
        )
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
        return None if dirty else head
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None


def execution_mode(
    suite: Discovered, decision: Report | None
) -> tuple[Literal["full", "subset"], list[str]]:
    if decision is None:
        return "full", []
    if digest(decision.model_dump(exclude={"digest"})) != decision.digest:
        return "full", ["INVALID_DECISION_DIGEST"]
    if decision.execution == "full":
        return "full", []
    ids = {t.id for t in suite.inventory.tests}
    if (
        decision.mode != "subset"
        or decision.fallback
        or not decision.selected
        or len(set(decision.selected)) != len(decision.selected)
        or not set(decision.selected) <= ids
        or set(decision.omitted) != ids - set(decision.selected)
        or decision.evidence.get("inventory") != digest(suite.inventory.model_dump())
    ):
        return "full", ["DECISION_INVENTORY_MISMATCH"]
    if decision.comparison.get("head") != current_clean_head(suite.root):
        return "full", ["STALE_OR_DIRTY_WORKSPACE"]
    return "subset", []


def execute(suite: Discovered, decision: Report | None = None) -> dict[str, object]:
    mode, fallbacks = execution_mode(suite, decision)
    attempts: list[dict[str, object]] = []
    observed_failure = False

    def run(mode: Literal["full", "subset"]) -> list[str]:
        nonlocal observed_failure
        statuses: list[str] = []
        for entry, runner, units in suite.runners:
            selected = (
                None
                if mode == "full"
                else {
                    u.id
                    for u in units
                    if decision is not None and u.id in decision.selected
                }
            )
            if selected == set():
                continue
            result = runner.run(units, selected)
            observed_failure |= "failed" in result.observed.values()
            attempts.append(
                {
                    "suite": entry.name,
                    "mode": mode,
                    "targets": {
                        u.id: u.target for u in units if u.id in result.expected
                    },
                    **asdict(result),
                }
            )
            statuses.append(result.status)
        return statuses

    statuses = run(mode)
    if (
        mode == "subset"
        and decision is not None
        and current_clean_head(suite.root) != decision.comparison.get("head")
    ):
        statuses.append("incomplete")
        fallbacks.append("WORKSPACE_CHANGED_DURING_RUN")
    if mode == "subset" and "incomplete" in statuses:
        fallbacks.append("INCOMPLETE_SUBSET_RESULTS")
        # Retain any observed failure even if the independent full retry passes.
        statuses = run("full")
        mode = "full"
        if observed_failure:
            statuses.append("failed")
    status = (
        "incomplete"
        if not statuses or "incomplete" in statuses
        else "failed"
        if "failed" in statuses
        else "passed"
    )
    report = {
        "schema_version": "1",
        "repository": suite.config.repository,
        "status": status,
        "execution": mode,
        "fallback": fallbacks,
        "inventory_digest": digest(suite.inventory.model_dump()),
        "decision_digest": decision.digest if decision else None,
        "attempts": attempts,
    }

    return RunReport.model_validate(report).model_dump()


def manifest(suite: Discovered) -> str:
    return json.dumps(suite.inventory.model_dump(), indent=2) + "\n"
