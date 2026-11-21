import json
import sys

import pytest

from smartci.adapters.runners import (
    AdapterError,
    PyReport,
    Runner,
    RunResult,
    Unit,
    invoke,
    reconcile,
)
from smartci.adapters.suite import discover, execute, execution_mode
from smartci.selection import Report, digest, finish


@pytest.fixture
def python_suite(tmp_path):
    root = tmp_path / "python"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = .\n")
    (root / "test_example.py").write_text(
        'import pytest\n@pytest.mark.parametrize("value", [1, 2], ids=["one", "two"] )\ndef test_value(value):\n    assert value > 0\n'
    )
    (tmp_path / "smartci.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "repository": "example",
                "suites": [{"name": "unit", "runner": "pytest", "path": "python"}],
            }
        )
    )
    return discover(tmp_path / "smartci.json")


def proposal(suite):
    ids = [t.id for t in suite.inventory.tests]
    return finish(
        Report(
            mode="subset",
            execution="subset",
            comparison={"head": "a" * 40},
            selected=ids[:1],
            omitted={i: "NO_IMPACT" for i in ids[1:]},
            reasons={ids[0]: ["IMPACTED"]},
            fallback=[],
            warnings=[],
            evidence={"inventory": digest(suite.inventory.model_dump())},
        )
    )


def test_real_pytest_parameterization_full_and_subset(python_suite):
    _, runner, units = python_suite.runners[0]
    assert len(units) == 2
    assert {u.target for u in units} == {
        "test_example.py::test_value[one]",
        "test_example.py::test_value[two]",
    }
    assert len({u.id for u in units}) == 2
    assert runner.discover() == units
    full = runner.run(units)
    assert full.status == "passed" and len(full.observed) == 2
    subset = runner.run(units, {units[0].id})
    assert subset.status == "passed" and list(subset.observed) == [units[0].id]
    with pytest.raises(AdapterError):
        runner.run(units, {"invented"})
    with pytest.raises(AdapterError):
        runner.run(units, set())


@pytest.mark.parametrize(
    "fixture, expected",
    [
        (
            'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    raise RuntimeError("setup failure")\n',
            "failed",
        ),
        (
            'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    yield\n    raise RuntimeError("teardown failure")\n',
            "failed",
        ),
        (
            'import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    pytest.skip("unavailable")\n',
            "incomplete",
        ),
    ],
)
def test_real_setup_teardown_and_skips(python_suite, fixture, expected):
    _, runner, units = python_suite.runners[0]
    (runner.root / "conftest.py").write_text(fixture)
    assert runner.run(units).status == expected


def test_missing_discovery_and_native_report(python_suite, monkeypatch):
    _, runner, units = python_suite.runners[0]
    monkeypatch.setattr("smartci.adapters.runners.invoke", lambda *a, **k: 0)
    with pytest.raises(AdapterError):
        runner.discover()
    assert runner.run(units).status == "incomplete"


def test_file_granularity_reconciles_every_case_and_discards_stale_results(
    python_suite, monkeypatch
):
    _, previous, _ = python_suite.runners[0]
    runner = Runner("pytest", previous.root, "repo", pytest_granularity="file")
    units = runner.discover()
    assert len(units) == 1 and len(runner.pytest_cases) == 2
    assert runner.run(units).status == "passed"
    assert len(runner.native_results) == 2
    missing = PyReport(
        collected=list(runner.pytest_cases[:1]),
        results={runner.pytest_cases[0]: "passed"},
        exit=0,
    )
    assert runner.pytest_results(missing, units, 0) == {}
    monkeypatch.setattr("smartci.adapters.runners.invoke", lambda *a, **k: 0)
    assert runner.run(units).status == "incomplete"
    assert runner.native_results == {}


def test_real_collection_failure_and_empty(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = .\n")
    runner = Runner("pytest", tmp_path, "repo")
    with pytest.raises(AdapterError):
        runner.discover()
    (tmp_path / "test_broken.py").write_text('raise RuntimeError("broken import")')
    with pytest.raises(AdapterError):
        runner.discover()


@pytest.mark.parametrize(
    "observed,code,status",
    [
        ({"case": "passed"}, 0, "passed"),
        ({"case": "failed"}, 1, "failed"),
        ({"case": "passed"}, 1, "incomplete"),
        ({"case": "skipped"}, 0, "incomplete"),
        ({}, 0, "incomplete"),
        ({"case": "passed", "extra": "passed"}, 0, "incomplete"),
    ],
)
def test_reconciliation(observed, code, status):
    assert (
        reconcile([Unit("id", "case", "test.py")], observed, code, 0).status == status
    )


def test_timeout_and_missing_executable(tmp_path):
    with pytest.raises(AdapterError, match="timed out"):
        invoke(
            [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, timeout=0
        )
    with pytest.raises(AdapterError, match="unavailable"):
        invoke([str(tmp_path / "not-an-executable")], tmp_path)


def test_shadow_and_invalid_decisions_force_full(python_suite, monkeypatch):
    monkeypatch.setattr(
        "smartci.adapters.suite.current_clean_head", lambda root: "a" * 40
    )
    decision = proposal(python_suite)
    assert execution_mode(python_suite, decision) == ("subset", [])
    shadow = finish(decision.model_copy(update={"execution": "full"}))
    assert execute(python_suite, shadow)["execution"] == "full"
    for change in (
        {"selected": []},
        {"selected": ["unknown"]},
        {"evidence": {}},
        {"omitted": {}},
        {"fallback": ["RISK"]},
    ):
        invalid = finish(decision.model_copy(update=change))
        assert execution_mode(python_suite, invalid)[0] == "full"
    assert (
        execution_mode(python_suite, decision.model_copy(update={"digest": "wrong"}))[0]
        == "full"
    )
    monkeypatch.setattr("smartci.adapters.suite.current_clean_head", lambda root: None)
    assert execution_mode(python_suite, decision)[1] == ["STALE_OR_DIRTY_WORKSPACE"]


def test_incomplete_subset_retries_unfiltered_full_without_erasing_failure(
    python_suite, monkeypatch
):
    monkeypatch.setattr(
        "smartci.adapters.suite.current_clean_head", lambda root: "a" * 40
    )
    calls = []

    def run(self, units, selected=None):
        calls.append(selected)
        if selected is not None:
            return RunResult(
                "incomplete", list(selected), {next(iter(selected)): "failed"}, 1, 0
            )
        return RunResult(
            "passed", [u.id for u in units], {u.id: "passed" for u in units}, 0, 0
        )

    monkeypatch.setattr(Runner, "run", run)
    result = execute(python_suite, proposal(python_suite))
    assert calls[0] is not None and calls[1] is None
    assert result["status"] == "failed"
    assert result["fallback"] == ["INCOMPLETE_SUBSET_RESULTS"]


def test_vitest_native_results(tmp_path):
    test = tmp_path / "one.test.ts"
    test.touch()
    runner = Runner("vitest", tmp_path, "repo")
    report = tmp_path / "results.json"
    entry = {
        "name": str(test),
        "assertionResults": [{"status": "passed"}, {"status": "failed"}],
    }
    report.write_text(json.dumps({"testResults": [entry]}))
    assert runner.vitest_results(report) == {"one.test.ts": "failed"}
    report.write_text(json.dumps({"testResults": [entry, entry]}))
    with pytest.raises(AdapterError):
        runner.vitest_results(report)
    entry["name"] = str(tmp_path.parent / "outside.test.ts")
    report.write_text(json.dumps({"testResults": [entry]}))
    with pytest.raises(AdapterError):
        runner.vitest_results(report)


@pytest.mark.parametrize(
    "body,expected",
    [
        ('<testcase name="one"/><testcase name="two"/>', "passed"),
        ('<testcase name="one"/><testcase name="two"><failure/></testcase>', "failed"),
        ('<testcase name="one"/><testcase name="two"><error/></testcase>', "failed"),
        ('<testcase name="one"/><testcase name="two"><skipped/></testcase>', "skipped"),
    ],
)
def test_junit_parameterized_native_report(tmp_path, body, expected):
    (tmp_path / "TEST-demo.ExampleTest.xml").write_text(
        f'<testsuite name="demo.ExampleTest" tests="2">{body}</testsuite>'
    )
    assert Runner("maven", tmp_path, "repo").java_results(tmp_path) == {
        "demo.ExampleTest": expected
    }


@pytest.mark.parametrize(
    "xml",
    [
        "<!DOCTYPE testsuite><testsuite/>",
        '<testsuite name="empty" tests="0"/>',
        '<testsuite name="bad" tests="2"><testcase/></testsuite>',
    ],
)
def test_bad_junit_reports(tmp_path, xml):
    (tmp_path / "TEST-bad.xml").write_text(xml)
    with pytest.raises(AdapterError):
        Runner("maven", tmp_path, "repo").java_results(tmp_path)


def test_unsupported_java_profiles_and_dynamic_tests(tmp_path):
    runner = Runner("maven", tmp_path, "repo")
    pom = tmp_path / "pom.xml"
    pom.write_text("<project><profiles/></project>")
    with pytest.raises(AdapterError):
        runner.discover()
    pom.write_text("<project/>")
    source = tmp_path / "src/test/java/DynamicTest.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package demo;\nclass DynamicTest { @TestFactory void generated() {} }"
    )
    with pytest.raises(AdapterError):
        runner.discover()


def test_suite_path_escape(python_suite, tmp_path):
    from smartci.adapters.suite import SuiteConfig

    config = python_suite.config.model_dump()
    config["suites"][0]["path"] = "../outside"
    with pytest.raises(ValueError):
        SuiteConfig.model_validate(config)
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    config["suites"][0]["path"] = "escape"
    (tmp_path / "smartci.json").write_text(json.dumps(config))
    with pytest.raises(AdapterError):
        discover(tmp_path / "smartci.json")


def test_cli_full_and_invalid_decision(python_suite, tmp_path, monkeypatch):
    from smartci.cli import main

    config = tmp_path / "smartci.json"
    output = tmp_path / "execution.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "run",
            "--config",
            str(config),
            "--output",
            str(output),
            "--decision",
            str(tmp_path / "missing"),
        ],
    )
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["status"] == "passed" and report["execution"] == "full"
    assert report["fallback"] == ["INVALID_OR_UNAVAILABLE_DECISION"]
    assert len(report["attempts"][0]["observed"]) == 2


def test_cli_discovery_failure_is_not_success(python_suite, tmp_path, monkeypatch):
    from smartci.cli import main

    (tmp_path / "python/test_example.py").write_text("broken syntax !!!")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "run",
            "--config",
            str(tmp_path / "smartci.json"),
            "--output",
            str(tmp_path / "output.json"),
        ],
    )
    assert main() == 2


def test_workspace_change_during_subset_forces_full(python_suite, monkeypatch):
    heads = iter(["a" * 40, None])
    monkeypatch.setattr(
        "smartci.adapters.suite.current_clean_head", lambda root: next(heads)
    )
    calls = []

    def run(self, units, selected=None):
        calls.append(selected)
        chosen = units if selected is None else [u for u in units if u.id in selected]
        return RunResult(
            "passed", [u.id for u in chosen], {u.id: "passed" for u in chosen}, 0, 0
        )

    monkeypatch.setattr(Runner, "run", run)
    result = execute(python_suite, proposal(python_suite))
    assert result["status"] == "passed" and result["execution"] == "full"
    assert "WORKSPACE_CHANGED_DURING_RUN" in result["fallback"]
    assert calls[0] is not None and calls[1] is None


def test_cli_real_test_failure_exits_one(python_suite, tmp_path, monkeypatch):
    from smartci.cli import main

    (tmp_path / "python/test_example.py").write_text(
        "def test_failure():\n    assert False\n"
    )
    output = tmp_path / "failed.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "run",
            "--config",
            str(tmp_path / "smartci.json"),
            "--output",
            str(output),
        ],
    )
    assert main() == 1
    assert json.loads(output.read_text())["status"] == "failed"


def test_custom_vitest_config_requires_adapter_extension(tmp_path):
    (tmp_path / "vitest.config.ts").write_text("export default {}")
    with pytest.raises(AdapterError, match="custom Vitest"):
        Runner("vitest", tmp_path, "repo").vitest_command()


def test_execution_schema_rejects_green_report_with_observed_failure(python_suite):
    from smartci.adapters.results import RunReport

    report = execute(python_suite)
    RunReport.model_validate(report)
    attempt = report["attempts"][0]
    attempt["observed"][attempt["expected"][0]] = "failed"
    with pytest.raises(ValueError):
        RunReport.model_validate(report)


def test_utf16_xml_entities_are_rejected(tmp_path):
    raw = '<!DOCTYPE testsuite [<!ENTITY value "expanded">]><testsuite name="example" tests="1"><testcase name="&value;"/></testsuite>'
    (tmp_path / "TEST-example.xml").write_bytes(raw.encode("utf-16"))
    with pytest.raises(AdapterError):
        Runner("maven", tmp_path, "repo").java_results(tmp_path)
