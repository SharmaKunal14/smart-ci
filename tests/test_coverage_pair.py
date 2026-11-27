import importlib.util
import json
from pathlib import Path

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
                    "native_case_count": len(ids),
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
