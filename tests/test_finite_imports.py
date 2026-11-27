"""Finite import choices widen impact; arbitrary uncertainty still runs all."""

import pytest
from test_discovery import (
    analyse,
    collect,
    commit,
    config,
    plan,
    repository,  # noqa: F401 -- shared native repository fixture
    selected_paths,
)

from smartci.contracts import Inventory
from smartci.contracts import TestUnit as UnitContract
from smartci.discovery.planning import required_full_from_head
from smartci.discovery.python_graph import node_id
from smartci.selection import Changes, Graph, SelectionPolicy, select

LOADER = "from importlib import import_module as load\ndef choose(index):\n    return load(('app.alpha', 'app.beta')[index])\n"


def files(loader=LOADER):
    return {
        "app/__init__.py": "",
        "app/alpha.py": "VALUE = 1\n",
        "app/beta.py": "VALUE = 2\n",
        "app/other.py": "VALUE = 3\n",
        "app/loader.py": loader,
        "app/consumer.py": "from .loader import choose\n",
        "tests/__init__.py": "",
        "tests/test_loader.py": "from app.loader import choose\n",
        "tests/test_consumer.py": "from app.consumer import choose\n",
        "tests/test_other.py": "from app.other import VALUE\n",
    }


def graph(source, commit_id):
    analysis = analyse(source)
    return Graph(
        schema_version="1",
        repository=config().repository,
        commit=commit_id,
        complete=not analysis.gaps,
        unsupported=bool(analysis.gaps),
        owners={p: node_id(p) for p in source},
        dependencies={
            node_id(p): sorted(node_id(d) for d in deps)
            for p, deps in analysis.dependencies.items()
        },
        tests={p: node_id(p) for p in source if p.startswith("tests/test_")},
    )


def decision(base_files, head_files, changed, must_run=()):
    common = {"schema_version": "1", "repository": config().repository}
    base, head = graph(base_files, "a" * 40), graph(head_files, "b" * 40)
    inventory = Inventory(
        **common,
        complete=True,
        environment="c" * 64,
        tests=[
            UnitContract(id=p, path=p, runner="pytest", granularity="file")
            for p in sorted(head.tests)
        ],
    )
    return select(
        Changes(**common, base=base.commit, head=head.commit, paths=changed),
        inventory,
        base,
        head,
        SelectionPolicy(**common, mode="selective", must_run=list(must_run)),
    )


@pytest.mark.parametrize("changed", ["app/alpha.py", "app/beta.py", "app/loader.py"])
def test_every_candidate_and_transitive_consumer_widens_selection(changed):
    source = files()
    report = decision(source, source, [changed])
    assert report.execution == "subset" and not report.fallback
    assert report.selected == ["tests/test_consumer.py", "tests/test_loader.py"]
    assert set(report.omitted) == {"tests/test_other.py"}
    reverse = dict(reversed(list(source.items())))
    assert decision(reverse, reverse, [changed]) == report


@pytest.mark.parametrize(
    "loader",
    [
        LOADER,
        LOADER.replace(
            "from importlib import import_module as load", "import importlib as library"
        ).replace("load(", "library.import_module("),
    ],
)
def test_provenance_enumerates_all_targets_and_initializers(loader):
    result = analyse(files(loader))
    assert not result.gaps
    assert {i.module for i in result.imports if i.resolution == "bounded_local"} == {
        "app.alpha",
        "app.beta",
    }
    assert {e.target for e in result.edges if e.kind == "bounded_import"} == {
        "app/__init__.py",
        "app/alpha.py",
        "app/beta.py",
    }


def test_removed_and_renamed_candidates_keep_base_dependencies():
    before = files()
    after = files(LOADER.replace("'app.alpha', 'app.beta'", "'app.beta', 'app.beta'"))
    # A removed edge remains relevant even when only its old target is changed.
    assert decision(before, after, ["app/alpha.py"]).selected == [
        "tests/test_consumer.py",
        "tests/test_loader.py",
    ]
    after = files(LOADER.replace("app.alpha", "app.renamed"))
    after["app/renamed.py"] = after.pop("app/alpha.py")
    assert decision(before, after, ["app/alpha.py", "app/renamed.py"]).selected == [
        "tests/test_consumer.py",
        "tests/test_loader.py",
    ]
    assert decision(
        before, before, ["app/alpha.py"], ["tests/test_other.py"]
    ).selected == sorted(graph(before, "a" * 40).tests)
    for test_change in ("tests/test_new.py", "tests/test_other.py"):
        after = before | {test_change: "def test_independent(): pass\n"}
        assert (
            test_change
            in decision(before, after, ["app/alpha.py", test_change]).selected
        )


@pytest.mark.parametrize(
    "expression",
    [
        "load(name)",
        "load(names[index])",
        "load(['app.alpha', 'app.beta'][index])",
        "load(('app.alpha', unknown)[index])",
        "load(('app.alpha', 'unknown.module')[index])",
        "load(('app.alpha', 'sys')[index])",
        "load(('.alpha', '.beta')[index], package='app')",
        "load(('app.alpha', 'app.beta')[index], package='app')",
        "load(('app.alpha', *names)[index])",
        "load(('app.alpha', 'app.beta')[index:])",
        "load(('app.alpha', 'app.beta')[get_index()])",
        "load((" + ",".join(["'app.alpha'"] * 33) + ",)[index])",
    ],
)
def test_arbitrary_or_unsupported_targets_still_require_full(expression):
    source = files(
        "from importlib import import_module as load\ndef choose(index):\n    return "
        + expression
    )
    assert "DYNAMIC_IMPORT" in {g.code for g in analyse(source).gaps}
    result = decision(source, source, ["app/other.py"])
    assert result.execution == "full" and result.fallback == ["INCOMPLETE_EVIDENCE"]


@pytest.mark.parametrize(
    "extra",
    [
        "load = other\n",
        "copy = load\n",
        "use(load)\n",
        "def shadow(load): pass\n",
        "del load\n",
        "from app import *\n",
        "from app import other as load\n",
        "try: pass\nexcept Exception as load: pass\n",
        "match value:\n    case {'a': load}: pass\n",
        "exec(source)\n",
        "import sys\nsys.path.append(path)\n",
        "import subprocess\nsubprocess.run(command)\n",
        "pytest_plugins = ['unknown']\n",
    ],
)
def test_escaping_shadowed_loader_and_global_unknowns_are_not_scoped(extra):
    source = files(LOADER + extra)
    result = decision(source, source, ["app/other.py"])
    assert result.execution == "full" and not result.omitted


def test_module_alias_escape_mutation_and_local_importlib_are_not_supported():
    loader = LOADER.replace(
        "from importlib import import_module as load", "import importlib as library"
    ).replace("load(", "library.import_module(")
    for extra in [
        "library.import_module = other\n",
        "copy = library\n",
        "use(library)\n",
    ]:
        assert analyse(files(loader + extra)).gaps
    for source in [
        files() | {"importlib.py": ""},
        files() | {"importlib/__init__.py": ""},
    ]:
        assert "DYNAMIC_IMPORT" in {g.code for g in analyse(source).gaps}


def test_unknown_in_either_revision_and_global_configuration_still_run_full():
    bounded = files()
    arbitrary = files(LOADER.replace("('app.alpha', 'app.beta')[index]", "name"))
    for before, after in [(bounded, arbitrary), (arbitrary, bounded)]:
        result = decision(before, after, ["app/other.py"])
        assert result.execution == "full"
        assert result.fallback == ["INCOMPLETE_EVIDENCE"]
    assert decision(bounded, bounded, ["pyproject.toml"]).fallback == ["RISK_PATH"]


def test_native_discovery_audit_and_execution_keep_real_failure(repository):  # noqa: F811
    (repository / "app/checkout.py").write_text(
        "from importlib import import_module as load\n"
        "def checkout():\n    return load(('app.auth', 'app.shared')[0]).allowed()\n"
    )
    commit(repository)
    base, baseline_runner, baseline_units = collect(repository, config())
    assert baseline_runner.run(baseline_units).status == "passed"
    (repository / "app/auth.py").write_text("def allowed(): return False\n")
    commit(repository)
    head, runner, units = collect(repository, config())
    policy = SelectionPolicy(
        schema_version="1", repository=config().repository, mode="selective"
    )
    report = plan(repository, base, head, policy)
    assert report == plan(repository, base, head, policy)
    assert required_full_from_head(repository, base.graph.commit, head, policy) is None
    assert report.execution == "subset" and not report.fallback
    assert selected_paths(report, head) == {
        "tests/test_auth.py",
        "tests/test_checkout.py",
    }
    assert len([w for w in report.warnings if w.startswith("BOUNDED_IMPORT:")]) == 2
    subset = runner.run(units, set(report.selected))
    subset_failures = {
        c for c, outcome in runner.native_results.items() if outcome == "failed"
    }
    full = runner.run(units)
    assert subset.status == full.status == "failed"
    assert subset.returncode == full.returncode == 1
    assert subset_failures == {
        c for c, outcome in runner.native_results.items() if outcome == "failed"
    }
    assert len(subset_failures) == 3
