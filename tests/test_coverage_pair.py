import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def pair(monkeypatch):
    directory = Path(__file__).parents[1] / "examples/textual"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "coverage_pair", directory / "coverage_pair.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_checks_identities_and_selected_scope(pair):
    ids = [
        "tests/test_a.py::test_value[a::b]",
        "tests/test_b.py::TestThing::test_other",
    ]
    actual = {("tests.test_a", "test_value[a::b]"): ("passed", None)}
    assert not pair.reconcile_inventory(ids, actual, None)
    assert pair.reconcile_inventory(ids, actual, ["tests/test_a.py"])
    assert not pair.reconcile_inventory(
        ids, {("tests.test_a", "unrelated"): ("passed", None)}, ["tests/test_a.py"]
    )
    with pytest.raises(ValueError):
        pair.reconcile_inventory([ids[0], ids[0]], actual, None)


def test_receipt_does_not_certify_partial_or_contradictory_results(pair, tmp_path):
    (tmp_path / "coverage.xml").write_text(
        '<coverage><class filename="a.py"><line number="1" hits="0"/></class></coverage>'
    )
    (tmp_path / "head-cases.json").write_text(
        json.dumps(["tests/test_a.py::test_one", "tests/test_a.py::test_two"])
    )
    (tmp_path / "junit.xml").write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_a" name="test_one"/></testsuite></testsuites>'
    )
    execution = {"head": "a" * 40, "exit_code": 0, "targets": None, "execution": "full"}

    def collection():
        ids = json.loads((tmp_path / "head-cases.json").read_text())
        (tmp_path / "head-compatibility.json").write_text(
            json.dumps(
                {
                    "commit": execution["head"],
                    "native_cases_digest": pair.canonical_digest(ids),
                    "cases": len(ids),
                }
            )
        )

    collection()
    assert pair.receipt(tmp_path, execution, {}, "123")["inventory_reconciled"] is False
    (tmp_path / "head-cases.json").write_text(json.dumps(["tests/test_a.py::test_one"]))
    with pytest.raises(ValueError, match="inventory revision or digest"):
        pair.receipt(tmp_path, execution, {}, "123")
    collection()
    assert pair.receipt(tmp_path, execution, {}, "123")["inventory_reconciled"] is True
    execution["exit_code"] = 124
    assert pair.receipt(tmp_path, execution, {}, "123")["inventory_reconciled"] is False


def test_workflow_never_exposes_model_credentials_or_changes_test_commands():
    workflow = Path("examples/textual/coverage-workflow.yml").read_text()
    assert "mode: [native, smart]" in workflow
    assert "secrets." not in workflow
    assert "SMARTCI_DISABLE_MODEL_CALLS: '1'" in workflow
    assert "contents: read" in workflow and "contents: write" not in workflow
    assert "persist-credentials: true" not in workflow
    assert "coverage_pair.py" in workflow
    assert "continue-on-error" not in workflow
    assert "--skip-coverage-report" in workflow


@pytest.mark.parametrize("native_exit", [0, 1])
def test_deferred_report_never_runs_and_preserves_native_exit(
    pair, tmp_path, monkeypatch, native_exit
):
    root, output = tmp_path / "repo", tmp_path / "output"
    root.mkdir()
    monkeypatch.chdir(root)
    head = "b" * 40
    monkeypatch.setattr(pair, "profile", lambda: {"python": "fixture"})
    monkeypatch.setattr(pair.subprocess, "check_output", lambda *a, **kw: head.encode())
    commands = []

    def command(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pair.subprocess, "run", command)

    def native(argv):
        (output / "execution.json").write_text(
            json.dumps({"exit_code": native_exit, "execution": "full"})
        )
        return native_exit

    monkeypatch.setattr(pair.benchmark, "main", native)
    monkeypatch.setattr(
        "sys.argv",
        [
            "pair",
            "--mode",
            "smart",
            "--base",
            "a" * 40,
            "--head",
            head,
            "--output",
            str(output),
            "--planner-python",
            "/tool/bin/python",
            "--skip-coverage-report",
        ],
    )
    assert pair.main() == native_exit
    assert all(cmd == ["git", "diff", "--exit-code", "HEAD"] for cmd in commands)
    execution = json.loads((output / "execution.json").read_text())
    assert execution["reporting_deferred"] is True
    assert execution["reporting_seconds"] == 0
    assert execution["reporting_exit"] is None
    assert execution["exit_code"] == native_exit
