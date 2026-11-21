"""Machine-readable collection/results without parsing terminal output."""

import json
import os
from pathlib import Path

import pytest

_collected: list[str] = []
_results: dict[str, str] = {}
_skip_reasons: dict[str, str] = {}


def pytest_collection_finish(session: pytest.Session) -> None:
    _collected.extend(item.nodeid for item in session.items)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed:
        _results[report.nodeid] = "failed"
    elif report.skipped and _results.get(report.nodeid) != "failed":
        _results[report.nodeid] = "skipped"
        if isinstance(report.longrepr, tuple) and not hasattr(report, "wasxfail"):
            _skip_reasons[report.nodeid] = str(report.longrepr[2]).removeprefix(
                "Skipped: "
            )[:1000]
    elif report.when == "call" and report.passed:
        _results.setdefault(report.nodeid, "passed")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    plugins = sorted(
        {
            dist.project_name.lower()
            for _, dist in session.config.pluginmanager.list_plugin_distinfo()
        }
    )
    Path(os.environ["SMARTCI_REPORT"]).write_text(
        json.dumps(
            {
                "collected": _collected,
                "results": _results,
                "exit": exitstatus,
                "plugins": plugins,
                "skip_reasons": _skip_reasons,
            }
        )
    )
