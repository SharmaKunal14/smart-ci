import hashlib
import json
import subprocess

import pytest
from pydantic import ValidationError
from test_investigation import repository  # noqa: F401 -- shared pytest fixture

from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.change_scope import compare
from smartci.investigation.engine import investigate
from smartci.investigation.models import ActionEnvelope, CompareSource, Limits, Propose
from smartci.investigation.replay import ChangeScopeReplay


def scope(before, after):
    return compare("src/example.py", before.encode(), after.encode())


@pytest.fixture
def case(request):
    return request.getfixturevalue("repository")


def test_method_body_and_nested_function_changes_have_exact_boundaries():
    before = "class A:\n    @decorate\n    def f(self):\n        return 1\n"
    result = scope(before, before.replace("return 1", "return 2"))
    assert result["classification"] == "function_body_only"
    changed = result["changed_callables"]
    assert len(changed) == 1 and changed[0]["name"] == "A.f"
    assert changed[0]["base"]["entry_line"] == 2
    assert changed[0]["base"]["end_line"] == 4
    assert changed[0]["decorated"] and changed[0]["class_member"]
    assert result["omission_authorized"] is False
    assert result["dependency_completeness_established"] is False
    nested = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
    result = scope(nested, nested.replace("return 1", "return 2"))
    assert [item["name"] for item in result["changed_callables"]] == ["outer"]


@pytest.mark.parametrize(
    "before,after",
    [
        ("PATTERN = 'old'\n", "PATTERN = 'new'\n"),
        ("def f(x=1): return x\n", "def f(x=2): return x\n"),
        ("def f(x: int): return x\n", "def f(x: str): return x\n"),
        ("@one\ndef f(): return 1\n", "@two\ndef f(): return 1\n"),
        ("def f(): return 1\n", "async def f(): return 1\n"),
        ("def f(): return 1\n", "def renamed(): return 1\n"),
        ("def f(): return 1\n", ""),
        ("", "def added(): return 1\n"),
        (
            "def f():\n    'old doc'\n    return 1\n",
            "def f():\n    'new doc'\n    return 1\n",
        ),
        (
            "class A(B):\n    def f(self): return 1\n",
            "class A(C):\n    def f(self): return 1\n",
        ),
        ("class A:\n    X = 1\n", "class A:\n    X = 2\n"),
        ("if flag:\n    def f(): return 1\n", "if flag:\n    def f(): return 2\n"),
        ("def f(): return 1\nx = 0\n", "def f(): return 2\nx = 1\n"),
    ],
)
def test_module_headers_declarations_and_opaque_scopes_are_not_body_only(before, after):
    assert scope(before, after)["classification"] == "module_or_definition_change"


def test_duplicate_method_names_keep_occurrences_separate():
    before = "class A:\n    @property\n    def f(self): return 1\n    @f.setter\n    def f(self, value): self.x = value\n"
    result = scope(before, before.replace("self.x = value", "self.x = value + 1"))
    assert result["classification"] == "function_body_only"
    assert [
        (row["name"], row["occurrence"]) for row in result["changed_callables"]
    ] == [("A.f", 1)]


def test_comments_and_formatting_do_not_claim_behavior_equivalence():
    result = scope("def f(): return 1\n", "# changed source\ndef f():\n    return 1\n")
    assert result["classification"] == "syntax_unchanged"
    assert result["omission_authorized"] is False
    assert result["semantics"] == "syntactic_change_scope_only"
    assert scope("x = 1\n", "x = 1\n")["classification"] == "identical_source"


def test_syntax_errors_limits_and_no_source_execution(tmp_path, monkeypatch):
    assert scope("x = 1", "def :")["classification"] == "unsupported"
    path = tmp_path / "must-not-exist"
    source = f"from pathlib import Path\nPath({str(path)!r}).touch()\ndef f(): return 'secret-value'\n"
    result = scope(source, source.replace("secret-value", "new-secret-value"))
    assert not path.exists()
    assert "secret-value" not in json.dumps(result)
    monkeypatch.setattr("smartci.investigation.change_scope.MAX_NODES", 3)
    assert scope(source, source)["classification"] == "unsupported"


def test_callable_and_output_bounds(monkeypatch):
    before = "def f(): return 1\ndef g(): return 1\n"
    after = before.replace("return 1", "return 2")
    monkeypatch.setattr("smartci.investigation.change_scope.MAX_CHANGED", 1)
    result = scope(before, after)
    assert len(result["changed_callables"]) == 1 and result["callables_truncated"]
    monkeypatch.setattr("smartci.investigation.change_scope.MAX_FUNCTIONS", 1)
    assert scope(before, after)["classification"] == "unsupported"


@pytest.mark.parametrize("path", ["../private.py", "/private.py", "a//b.py", "a\\b.py"])
def test_action_rejects_paths_and_caller_selected_revisions(path):
    with pytest.raises(ValidationError):
        ActionEnvelope.model_validate({"kind": "compare_source", "path": path})


@pytest.mark.parametrize(
    "claim",
    [
        {"revision": "a" * 40},
        {"classification": "function_body_only"},
        {"complete": True},
    ],
)
def test_comparison_does_not_accept_caller_chosen_revision_or_authority(claim):
    with pytest.raises(ValidationError):
        ActionEnvelope.model_validate(
            {"kind": "compare_source", "path": "src/core.py", **claim}
        )


def test_broker_binds_both_revisions_and_refuses_comparison_as_edge_evidence(
    case,
):
    root, inputs = case
    path = "src/core.py"
    (root / path).write_text("VALUE = 2\n")
    subprocess.run(
        ["git", "-C", str(root), "add", path], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Change",
        ],
        check=True,
        capture_output=True,
    )
    head = (
        subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    inputs.head.commit = inputs.changes.head = head
    inputs.sources[head] = inputs.sources[inputs.base.commit] | {
        path: hashlib.sha256(b"VALUE = 2\n").hexdigest()
    }
    broker = Broker(root, inputs, PythonImports(["src"]), Limits())
    report = broker.compare_source(CompareSource(kind="compare_source", path=path))
    assert report["classification"] == "module_or_definition_change"
    assert report["comparison"] == {"base": inputs.base.commit, "head": head}
    assert report["source_digests"]["base"] != report["source_digests"]["head"]
    with pytest.raises(ValueError, match="matching evidence"):
        broker.verify(
            Propose(
                kind="propose",
                revision=head,
                path=path,
                target="src/consumer.py",
                line=1,
                relation="python_absolute_import",
                evidence=report["digest"],
            )
        )
    inputs.sources[head][path] = "f" * 64
    broker = Broker(root, inputs, PythonImports(["src"]), Limits())
    with pytest.raises(ValueError, match="source digest"):
        broker.compare_source(CompareSource(kind="compare_source", path=path))


def test_unrelated_path_and_source_budget_are_rejected(case):
    root, inputs = case
    broker = Broker(root, inputs, PythonImports(["src"]), Limits())
    with pytest.raises(ValueError, match="recorded change"):
        broker.compare_source(
            CompareSource(kind="compare_source", path="src/consumer.py")
        )
    assert broker.bytes_read == 0
    broker = Broker(root, inputs, PythonImports(["src"]), Limits(source_bytes=1))
    with pytest.raises(ValueError, match="budget"):
        broker.compare_source(CompareSource(kind="compare_source", path="src/core.py"))


def test_scope_replay_retains_unknowns_full_fallback_and_input_data(case):
    root, inputs = case
    inputs.base.complete = False
    inputs.unresolved = ["DYNAMIC_IMPORT:src/core.py:1"]
    original = inputs.model_dump_json()

    def run():
        return investigate(
            inputs,
            Broker(root, inputs, PythonImports(["src"]), Limits()),
            ChangeScopeReplay(),
            Limits(),
        )

    report = run()
    assert report == run()
    assert report["status"] == "finished"
    assert report["final"]["execution"] == "full"
    assert report["unresolved"] == inputs.unresolved
    assert report["accepted_graph"]["evidence"] == []
    assert report["model_calls"] == 0
    assert report["trace"][0]["kind"] == "compare_source"
    assert inputs.model_dump_json() == original


def test_scope_replay_preserves_independent_baseline_and_mandatory_tests(case):
    root, inputs = case
    report = investigate(
        inputs,
        Broker(root, inputs, PythonImports(["src"]), Limits()),
        ChangeScopeReplay(),
        Limits(),
    )
    assert report["final"]["selected"] == report["baseline"]["selected"]
    assert "tests/test_other.py" in report["final"]["selected"]


def test_cli_scope_replay_uses_fixed_comparison(case, tmp_path, monkeypatch):
    from smartci.cli import main

    root, inputs = case
    input_path = tmp_path / "input.json"
    output = tmp_path / "scope.json"
    input_path.write_text(inputs.model_dump_json())
    monkeypatch.setattr(
        "sys.argv",
        [
            "smartci",
            "investigate",
            "--inputs",
            str(input_path),
            "--repo",
            str(root),
            "--module-root",
            "src",
            "--provider",
            "scope-replay",
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    report = json.loads(output.read_bytes())
    assert report["trace"][0]["result"]["comparison"] == {
        "base": inputs.base.commit,
        "head": inputs.head.commit,
    }
    assert report["model_calls"] == 0
