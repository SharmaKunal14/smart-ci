import json
import subprocess

import pytest
from pydantic import ValidationError

from smartci.contracts import Inventory
from smartci.git_changes import GitError, changes_from_git
from smartci.selection import Changes, Coverage, Graph, SelectionPolicy, select

A = "a" * 40
B = "b" * 40


def inputs():
    common = {"schema_version": "1", "repository": "example/repo"}
    inventory = Inventory.model_validate(
        common
        | {
            "complete": True,
            "environment": "c" * 64,
            "tests": [
                {
                    "id": name,
                    "path": f"tests/{name}.py",
                    "runner": "pytest",
                    "granularity": "case",
                }
                for name in ["auth", "checkout", "other"]
            ],
        }
    )
    graph = Graph.model_validate(
        common
        | {
            "commit": A,
            "complete": True,
            "owners": {
                "auth.py": "auth",
                "checkout.py": "checkout",
                "other.py": "other",
            },
            "dependencies": {"auth": [], "checkout": ["auth"], "other": []},
            "tests": {name: name for name in ["auth", "checkout", "other"]},
        }
    )
    return (
        Changes.model_validate(common | {"base": A, "head": B, "paths": ["auth.py"]}),
        inventory,
        graph,
        graph.model_copy(update={"commit": B}, deep=True),
        SelectionPolicy.model_validate(common),
    )


def test_transitive_deterministic_and_shadow():
    data = inputs()
    report = select(*data)
    assert report.selected == ["auth", "checkout"]
    assert report.execution == "full"
    assert report.omitted == {"other": "NO_IMPACT_FOUND_UNDER_RECORDED_EVIDENCE"}
    assert report.digest == select(*data).digest


def test_removed_edges_cycles_and_monotonic_additions():
    changes, inv, base, head, policy = inputs()
    head.dependencies["checkout"] = []
    assert select(changes, inv, base, head, policy).selected == ["auth", "checkout"]
    head.dependencies["auth"] = ["checkout"]
    head.dependencies["other"] = ["checkout"]
    assert select(changes, inv, base, head, policy).selected == [
        "auth",
        "checkout",
        "other",
    ]


@pytest.mark.parametrize(
    "path,code",
    [
        ("new.py", "UNMAPPED_PATH"),
        ("config/app.json", "RISK_PATH"),
        ("uv.lock", "RISK_PATH"),
        ("migrations/001.sql", "RISK_PATH"),
        (".github/workflows/test.yml", "RISK_PATH"),
    ],
)
def test_risk_and_unknown_paths(path, code):
    changes, *rest = inputs()
    report = select(changes.model_copy(update={"paths": [path]}), *rest)
    assert report.mode == "full"
    assert report.fallback == [code]


def test_missing_stale_and_unsupported():
    changes, inv, base, head, policy = inputs()
    for field, value, code in [
        ("complete", False, "INCOMPLETE_EVIDENCE"),
        ("commit", A, "STALE_GRAPH"),
        ("unsupported", True, "UNSUPPORTED_ANALYSIS"),
        ("repository", "other", "REPOSITORY_MISMATCH"),
    ]:
        assert select(
            changes, inv, base, head.model_copy(update={field: value}), policy
        ).fallback == [code]
    assert (
        select(
            changes, inv.model_copy(update={"complete": False}), base, head, policy
        ).mode
        == "full"
    )
    assert select(
        changes.model_copy(update={"paths": []}), inv, base, head, policy
    ).fallback == ["EMPTY_SELECTION"]


def test_mandatory_new_tests_and_coverage_only_add():
    changes, inv, base, head, policy = inputs()
    policy.must_run = ["other"]
    assert select(changes, inv, base, head, policy).selected == [
        "auth",
        "checkout",
        "other",
    ]
    policy.must_run = []
    del base.tests["other"]
    assert "other" in select(changes, inv, base, head, policy).selected
    base.tests["other"] = "other"
    coverage = Coverage(
        schema_version="1",
        repository="example/repo",
        commit=A,
        environment=inv.environment,
        complete=True,
        files={"other": ["auth.py"]},
    )
    assert "other" in select(changes, inv, base, head, policy, coverage).selected
    coverage.commit = B
    assert select(changes, inv, base, head, policy, coverage).warnings == [
        "OPTIONAL_COVERAGE_IGNORED"
    ]
    policy.require_coverage = True
    assert select(changes, inv, base, head, policy, coverage).mode == "full"
    assert select(changes, inv, base, head, policy).mode == "full"


def test_invalid_graph_and_missing_mandatory():
    changes, inv, base, head, policy = inputs()
    with pytest.raises(ValidationError):
        Graph.model_validate(
            head.model_dump() | {"dependencies": {"auth": ["missing"]}}
        )
    policy.must_run = ["absent"]
    assert select(changes, inv, base, head, policy).fallback == ["INVENTORY_MISMATCH"]


def git(repo, *args):
    return (
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        .stdout.decode()
        .strip()
    )


def test_git_renames_deletions_shallow_and_missing_history(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "old name.py").write_text("old contents\n")
    (repo / "deleted.py").write_text("delete me\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "mv", "old name.py", "new name.py")
    git(repo, "rm", "deleted.py")
    git(repo, "commit", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")
    assert changes_from_git(repo, base, head, "fixture").paths == [
        "deleted.py",
        "new name.py",
        "old name.py",
    ]
    with pytest.raises(GitError):
        changes_from_git(repo, "f" * 40, head, "fixture")
    with pytest.raises(GitError):
        changes_from_git(repo, "--help", head, "fixture")
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", repo.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(GitError):
        changes_from_git(clone, base, head, "fixture")


def test_cli_invalid_input_fails_to_full(tmp_path):
    output, audit = tmp_path / "selection.json", tmp_path / "audit.md"
    result = subprocess.run(
        [
            "smartci",
            "select",
            "--inventory",
            "missing",
            "--policy",
            "missing",
            "--base-graph",
            "missing",
            "--head-graph",
            "missing",
            "--output",
            str(output),
            "--audit",
            str(audit),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert json.loads(output.read_text())["execution"] == "full"
    assert "independent full-suite" in audit.read_text()
    result = subprocess.run(
        ["smartci", "explain", str(output)], check=False, capture_output=True
    )
    assert result.returncode == 0
    output.write_text(
        output.read_text().replace('"execution": "full"', '"execution": "subset"')
    )
    assert (
        subprocess.run(
            ["smartci", "explain", str(output)], check=False, capture_output=True
        ).returncode
        == 2
    )


def test_git_merge_base_and_symlink(tmp_path):
    repo = tmp_path / "history"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "base.py").write_text("base")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    ancestor = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "feature")
    (repo / "feature.py").write_text("feature")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feature")
    feature = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    (repo / "main.py").write_text("main")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "main")
    main = git(repo, "rev-parse", "HEAD")
    result = changes_from_git(repo, main, feature, "fixture")
    assert result.base == ancestor
    assert result.paths == ["feature.py"]
    git(repo, "merge", "feature", "--no-edit")
    merged = git(repo, "rev-parse", "HEAD")
    assert changes_from_git(repo, main, merged, "fixture").paths == ["feature.py"]
    (repo / "link").symlink_to("base.py")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "symlink")
    with pytest.raises(GitError):
        changes_from_git(repo, merged, git(repo, "rev-parse", "HEAD"), "fixture")


def test_cli_subset_and_write_failure(tmp_path):
    root = "fixtures/selection/"
    output = tmp_path / "selection.json"
    command = [
        "smartci",
        "select",
        "--inventory",
        root + "inventory.json",
        "--policy",
        root + "policy.json",
        "--base-graph",
        root + "base-graph.json",
        "--head-graph",
        root + "head-graph.json",
        "--changes",
        root + "narrow.json",
        "--output",
        str(output),
        "--audit",
        str(tmp_path / "audit.md"),
    ]
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    report = json.loads(output.read_text())
    assert report["selected"] == ["auth", "checkout"]
    assert report["execution"] == "full"
    command[-1] = str(output)
    assert subprocess.run(command, capture_output=True, check=False).returncode == 2
