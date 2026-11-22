"""Diagnostic reachability must not become selection or lose removed edges."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartci.contracts import Inventory
from smartci.selection import Changes, Graph, digest

SPEC = importlib.util.spec_from_file_location(
    "known_reachability",
    Path(__file__).parents[1] / "examples/textual/known_reachability.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def inputs():
    common = {"schema_version": "1", "repository": "fixture"}
    owners = {
        "app/auth.py": "auth",
        "app/checkout.py": "checkout",
        "tests/test_auth.py": "test_auth",
        "tests/test_checkout.py": "test_checkout",
        "tests/test_other.py": "test_other",
    }
    base_graph = Graph.model_validate(
        common
        | {
            "commit": "a" * 40,
            "complete": False,
            "unsupported": True,
            "owners": owners,
            "dependencies": {
                "auth": [],
                "checkout": ["auth"],
                "test_auth": ["auth"],
                "test_checkout": ["checkout"],
                "test_other": [],
            },
            "tests": {
                name: name for name in ["test_auth", "test_checkout", "test_other"]
            },
        }
    )
    inventory = Inventory.model_validate(
        common
        | {
            "complete": True,
            "environment": "e" * 64,
            "tests": [
                {
                    "id": name,
                    "path": f"tests/{name}.py",
                    "runner": "pytest",
                    "granularity": "file",
                }
                for name in base_graph.tests
            ],
        }
    )
    # Only the graph, inventory and revision identity are consumed by the diagnostic.
    base = SimpleNamespace(
        repository="fixture", graph=base_graph, inventory=inventory, digest="c" * 64
    )
    head = SimpleNamespace(
        repository="fixture",
        graph=base_graph.model_copy(update={"commit": "b" * 40}, deep=True),
        inventory=inventory,
        digest="d" * 64,
    )
    changes = Changes.model_validate(
        common | {"base": "a" * 40, "head": "b" * 40, "paths": ["app/auth.py"]}
    )
    return changes, base, head


def test_transitive_reachability_retains_removed_edges_and_never_authorizes_omissions():
    changes, base, head = inputs()
    head.graph.dependencies["checkout"] = []
    result = module.summarize(changes, base, head)
    aggregate = result["aggregate"]
    assert aggregate["reached_test_files"] == [
        "tests/test_auth.py",
        "tests/test_checkout.py",
    ]
    assert aggregate["test_files_not_reached"] == 1
    assert result["omission_authorized"] is False
    assert result["execution_required"] == "full"
    assert result["test_execution_performed"] is False
    assert result["ci_savings_demonstrated"] is False
    assert result["digest"] == digest(
        {k: v for k, v in result.items() if k != "digest"}
    )
    assert any(
        "app/auth.py -> app/checkout.py -> tests/test_checkout.py" in reason
        for witness in aggregate["witnesses"]
        for reason in witness["reasons"]
    )


def test_cycles_order_duplicates_and_input_immutability():
    changes, base, head = inputs()
    head.graph.dependencies["auth"] = ["checkout"]
    before = head.graph.model_dump()
    first = module.summarize(changes, base, head)
    head.graph.dependencies = dict(reversed(list(head.graph.dependencies.items())))
    changes.paths = ["app/auth.py", "app/auth.py"]
    assert module.summarize(changes, base, head) == first
    assert head.graph.model_dump() == before


def test_deleted_sources_and_unmapped_changes_do_not_disappear():
    changes, base, head = inputs()
    head.graph.owners.pop("app/auth.py")
    changes.paths.append("build/unknown.cfg")
    result = module.summarize(changes, base, head)
    assert result["unmapped_changed_paths"] == ["build/unknown.cfg"]
    assert result["aggregate"]["test_files_reached"] == 2
    assert len(result["per_mapped_changed_path"]) == 1


def test_empty_or_only_unknown_diff_cannot_authorize_skips():
    changes, base, head = inputs()
    for paths in ([], ["unknown.py"]):
        changes.paths = paths
        result = module.summarize(changes, base, head)
        assert result["aggregate"]["test_files_reached"] == 0
        assert result["omission_authorized"] is False
        assert result["execution_required"] == "full"


@pytest.mark.parametrize(
    "field,value", [("base", "f" * 40), ("head", "f" * 40), ("repository", "different")]
)
def test_mismatched_comparisons_rejected(field, value):
    changes, base, head = inputs()
    setattr(changes, field, value)
    with pytest.raises(ValueError, match="does not match"):
        module.summarize(changes, base, head)


def test_reporting_limits_do_not_reduce_reachable_counts(monkeypatch):
    changes, base, head = inputs()
    changes.paths.append("app/checkout.py")
    monkeypatch.setattr(module, "MAX_WITNESSES", 1)
    monkeypatch.setattr(module, "MAX_INDIVIDUAL_PATHS", 1)
    result = module.summarize(changes, base, head)
    assert result["individual_paths_truncated"] is True
    assert len(result["per_mapped_changed_path"]) == 1
    assert result["aggregate"]["witnesses_truncated"] is True
    assert result["aggregate"]["test_files_reached"] == 2


def test_long_witness_is_marked_without_losing_reachability():
    changes, base, head = inputs()
    previous = "auth"
    for number in range(70):
        current = f"chain_{number}"
        head.graph.owners[f"app/{current}.py"] = current
        head.graph.dependencies[current] = [previous]
        previous = current
    head.graph.dependencies["test_other"] = [previous]
    result = module.summarize(changes, base, head)["aggregate"]
    assert result["test_files_reached"] == 3
    other = next(w for w in result["witnesses"] if w["test_id"] == "test_other")
    assert other["reasons"] == ["DEPENDENCY_PATH_EXCEEDS_DISPLAY_LIMIT"]


@pytest.mark.parametrize("mode", ["native", "smart", "observe", "observe-scoped"])
def test_diagnostic_flag_cannot_launch_an_execution_mode(mode, tmp_path):
    output = tmp_path / "not-created"
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "examples/textual/benchmark.py"),
            "--mode",
            mode,
            "--base",
            "a" * 40,
            "--head",
            "b" * 40,
            "--output",
            str(output),
            "--diagnose-reachability",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "require plan-only mode" in completed.stderr
    assert not output.exists()
