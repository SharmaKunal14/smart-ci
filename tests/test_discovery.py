import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.adapters.runners import AdapterError, Runner
from smartci.cli import main
from smartci.discovery.collector import collect, environment_gaps
from smartci.discovery.models import Environment, PythonConfig, Snapshot
from smartci.discovery.planning import plan
from smartci.discovery.python_graph import Analysis
from smartci.selection import SelectionPolicy, digest


def config():
    return PythonConfig(
        schema_version="1",
        repository="example/python",
        source_roots=["."],
        test_roots=["tests"],
    )


def environment():
    return Environment(
        python="3.14.7",
        implementation="CPython",
        platform="test",
        machine="test",
        abi="test",
        observer_digest="0" * 64,
        distributions={"pytest": "9.2.0"},
        external_modules=["pytest"],
        available_modules=["pytest"],
        stdlib=sorted(sys.stdlib_module_names),
        native_roots={},
        import_hooks=[
            "_frozen_importlib.BuiltinImporter",
            "_frozen_importlib.FrozenImporter",
            "_frozen_importlib_external.PathFinder",
        ],
        hook_hashes={},
        ambient={},
        configuration={},
    )


def analyse(files, env=None):
    analysis = Analysis(
        {p: s.encode() for p, s in files.items()}, config(), env or environment()
    )
    analysis.analyse()
    return analysis


def test_child_script_without_import_edge_requires_full_plan(repository):
    (repository / "tests/test_child.py").write_text(
        "import subprocess\nimport sys\n"
        "def test_child():\n"
        "    subprocess.run([sys.executable, '-c', "
        "'from app.auth import allowed; assert allowed()'], check=True)\n"
    )
    commit(repository)
    base, _, _ = collect(repository, config())
    (repository / "app/auth.py").write_text("def allowed(): return False\n")
    commit(repository)
    head, _, _ = collect(repository, config())
    report = plan(
        repository,
        base,
        head,
        SelectionPolicy(
            schema_version="1", repository=config().repository, mode="selective"
        ),
    )
    assert any(
        g.code == "DYNAMIC_PROCESS" and g.path == "tests/test_child.py"
        for g in head.provenance.gaps
    )
    assert not base.graph.complete and not head.graph.complete
    assert report.execution == "full"
    assert report.fallback == ["INCOMPLETE_EVIDENCE"]
    assert set(report.selected) == {unit.id for unit in head.inventory.tests}


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "test snapshot")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path, monkeypatch):
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    ):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        ".gitignore": "__pycache__/\n.pytest_cache/\nignored/\n",
        "pytest.ini": "[pytest]\ntestpaths = tests\naddopts = --strict-markers -m 'not excluded'\nmarkers =\n    excluded: outside this native profile\n",
        "app/__init__.py": "",
        "app/auth.py": "def allowed():\n    return True\n",
        "app/checkout.py": "from .auth import allowed\ndef checkout():\n    return allowed()\n",
        "app/other.py": "def price():\n    return 3\n",
        "app/shared.py": "VALUE = 7\n",
        "tests/__init__.py": "",
        "tests/data.json": "{}\n",
        "tests/conftest.py": "import pytest\nfrom app.shared import VALUE\n@pytest.fixture\ndef shared():\n    return VALUE\n",
        "tests/test_auth.py": "import pytest\nfrom app.auth import allowed\n@pytest.mark.parametrize('value', [1, 2], ids=['one', 'two'])\ndef test_auth(value, shared):\n    assert allowed() and value > 0 and shared == 7\n",
        "tests/test_checkout.py": "from app.checkout import checkout\ndef test_checkout():\n    assert checkout()\n",
        "tests/test_other.py": "import pytest\nfrom app.other import price\ndef test_other():\n    assert price() == 3\n@pytest.mark.excluded\ndef test_out_of_scope():\n    assert False\n",
    }
    for name, source in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    git(root, "init", "-q")
    git(root, "config", "user.name", "Smart CI verification")
    git(root, "config", "user.email", "verification@example.invalid")
    commit(root)
    return root


def policy():
    return SelectionPolicy(
        schema_version="1", repository="example/python", mode="shadow"
    )


def selected_paths(report, snapshot):
    return {t.path for t in snapshot.inventory.tests if t.id in report.selected}


def resign(data):
    data["digest"] = digest({k: v for k, v in data.items() if k != "digest"})
    return Snapshot.model_validate(data)


def test_local_relative_reexports_cycles_and_package_initializers():
    files = {
        "app/__init__.py": "from .auth import allowed\n",
        "app/auth.py": "from . import checkout\ndef allowed(): return True\n",
        "app/checkout.py": "from .auth import allowed\n",
        "tests/__init__.py": "",
        "tests/test_auth.py": "from app import allowed\n",
    }
    result = analyse(files)
    assert not result.gaps
    assert "app/auth.py" in result.dependencies["app/checkout.py"]
    assert "app/checkout.py" in result.dependencies["app/auth.py"]
    assert "app/__init__.py" in result.dependencies["tests/test_auth.py"]
    assert (
        result.dependencies == analyse(dict(reversed(list(files.items())))).dependencies
    )
    assert result.edges == analyse(dict(reversed(list(files.items())))).edges


@pytest.mark.parametrize(
    "source,code",
    [
        ("import unavailable_dependency", "UNRESOLVED_IMPORT"),
        ("from app.missing import thing", "UNRESOLVED_LOCAL_IMPORT"),
        ("import importlib\nimportlib.import_module(name)", "DYNAMIC_IMPORT"),
        ("from importlib import import_module as load\nload(name)", "DYNAMIC_IMPORT"),
        ("__import__(name)", "DYNAMIC_IMPORT"),
        (
            "import importlib\nloader = importlib.import_module\nloader(name)",
            "DYNAMIC_IMPORT",
        ),
        (
            "from importlib import import_module as load\nloader = load",
            "DYNAMIC_IMPORT",
        ),
        (
            "import importlib\ngetattr(importlib, 'import_module')(name)",
            "DYNAMIC_IMPORT",
        ),
        ("import sys\nsys.modules[name] = value", "CUSTOM_MODULE_REGISTRY"),
        ("globals()[name]", "DYNAMIC_CODE"),
        ("exec(code)", "DYNAMIC_CODE"),
        ("import sys\nsys.path.append('plugins')", "CUSTOM_IMPORT_PATH"),
        ("def __getattr__(name): return None", "DYNAMIC_ATTRIBUTE_HOOK"),
        ("pytest_plugins = ['helper']", "LOCAL_PYTEST_PLUGIN"),
        ("broken syntax (", "PARSE_ERROR"),
    ],
)
def test_unsupported_analysis_is_explicit(source, code):
    result = analyse({"app/__init__.py": "", "app/entry.py": source})
    assert code in {g.code for g in result.gaps}
    assert all(g.path == "app/entry.py" for g in result.gaps)


def test_optional_external_and_type_checking_keep_local_edges():
    result = analyse(
        {
            "app/__init__.py": "",
            "app/auth.py": "",
            "app/entry.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app import auth\n    import typing_extensions\ntry:\n    __import__('optional_platform_shim')\nexcept ImportError:\n    pass\nimport sys\nif sys.version_info >= (3, 11):\n    import tomllib\nelse:\n    import tomli\n",
        }
    )
    assert not result.gaps
    assert "app/auth.py" in result.dependencies["app/entry.py"]
    assert {i.module for i in result.imports if i.resolution == "optional_absent"} == {
        "typing_extensions",
        "optional_platform_shim",
        "tomli",
    }
    env = environment()
    env.available_modules = ["unmanaged"]
    unresolved = analyse(
        {"entry.py": "try:\n    import unmanaged\nexcept ImportError:\n    pass\n"}, env
    )
    assert {g.code for g in unresolved.gaps} == {"UNRESOLVED_IMPORT"}


def test_reviewed_external_fixture_overrides_cannot_hide_local_dependencies():
    files = {
        "tests/__init__.py": "",
        "tests/test_fixture.py": "import sys\ndef fixture(monkeypatch):\n    module_name = '_platform_shim'\n    monkeypatch.setitem(sys.modules, module_name, None)\n",
    }
    unreviewed = analyse(files)
    assert "CUSTOM_MODULE_REGISTRY" in {g.code for g in unreviewed.gaps}
    reviewed_config = config().model_copy(
        update={"external_module_overrides": ["_platform_shim"]}
    )
    result = Analysis(
        {p: s.encode() for p, s in files.items()}, reviewed_config, environment()
    )
    result.analyse()
    assert not result.gaps
    assert any(i.resolution == "reviewed_external_override" for i in result.imports)
    result.files["_platform_shim.py"] = b"# newly local implementation\n"
    result.analyse()
    assert "CUSTOM_MODULE_REGISTRY" in {g.code for g in result.gaps}


def test_probe_lookup_answers_do_not_change_environment_identity():
    before = environment()
    after = before.model_copy(
        update={
            "available_modules": [*before.available_modules, "new_module"],
            "native_roots": {"new_module": "new_module.py"},
        }
    )
    assert before.identity() == after.identity()
    changed_tools = after.model_copy(update={"distributions": {"pytest": "different"}})
    assert before.identity() != changed_tools.identity()


def test_local_module_precedes_standard_library_and_namespace_is_not_guessed():
    result = analyse({"json.py": "", "entry.py": "import json\n"})
    assert "json.py" in result.dependencies["entry.py"]
    assert result.imports[0].resolution == "local"
    assert "UNSUPPORTED_NAMESPACE_PACKAGE" in {
        g.code for g in analyse({"namespace/module.py": ""}).gaps
    }


def test_environment_origin_hooks_plugins_and_ambient_gaps(monkeypatch):
    env = environment()
    env.native_roots = {"app": "external/app.py"}
    env.import_hooks.append("unknown.Finder")
    analysis = analyse({"app/__init__.py": ""}, env)
    runner = Runner("pytest", Path("."), "repo")
    runner.pytest_plugins = ("unknown_plugin",)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--last-failed")
    assert {g.code for g in environment_gaps(analysis, runner)} >= {
        "NATIVE_IMPORT_ORIGIN_MISMATCH",
        "CUSTOM_IMPORT_HOOK",
        "UNREVIEWED_PYTEST_PLUGIN",
        "AMBIENT_PYTEST_CONFIGURATION",
        "LOCAL_IMPORT_OUTSIDE_SCOPE",
    }


@pytest.mark.parametrize("root", ["../outside", "/etc", "a/../b", "a\\b", "a//b"])
def test_unsafe_collector_configuration(root):
    with pytest.raises(ValidationError):
        PythonConfig.model_validate(config().model_dump() | {"source_roots": [root]})


def test_native_configuration_fixtures_parameterization_and_repeatability(repository):
    first, runner, units = collect(repository, config())
    assert first.graph.complete, first.provenance.gaps
    assert len(units) == 3
    assert first.provenance.native_case_count == 4
    result = runner.run(units)
    assert result.status == "passed"
    assert len(runner.native_results) == 4
    assert all("out_of_scope" not in case for case in runner.native_results)
    second, _, _ = collect(repository, config())
    assert first.model_dump() == second.model_dump()
    assert first.provenance.edges
    assert all(
        e.source in first.provenance.sources and e.target in first.provenance.sources
        for e in first.provenance.edges
    )
    # Full discovery is still native pytest after the observation plugin is removed.
    native = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=repository,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert native.returncode == 0


def test_automatic_direct_transitive_and_new_import_planning(repository):
    base, _, _ = collect(repository, config())
    auth = repository / "app/auth.py"
    auth.write_text(auth.read_text() + "\n# upstream change\n")
    commit(repository)
    head, _, _ = collect(repository, config())
    narrow = plan(repository, base, head, policy())
    assert narrow.mode == "subset" and narrow.execution == "full"
    assert selected_paths(narrow, head) == {
        "tests/test_auth.py",
        "tests/test_checkout.py",
    }
    assert narrow == plan(repository, base, head, policy())
    assert any(
        "app/auth.py -> app/checkout.py -> tests/test_checkout.py" in reason
        for reasons in narrow.reasons.values()
        for reason in reasons
    )
    other = repository / "app/other.py"
    other.write_text("from .auth import allowed\n" + other.read_text())
    commit(repository)
    with_import, _, _ = collect(repository, config())
    auth.write_text(auth.read_text() + "# next upstream change\n")
    commit(repository)
    updated, _, _ = collect(repository, config())
    expanded = plan(repository, with_import, updated, policy())
    assert selected_paths(expanded, updated) == {
        "tests/test_auth.py",
        "tests/test_checkout.py",
        "tests/test_other.py",
    }
    assert any(
        "app/auth.py -> app/other.py -> tests/test_other.py" in reason
        for reasons in expanded.reasons.values()
        for reason in reasons
    )


def test_new_test_rename_and_removed_dependency_refresh(repository):
    base, _, _ = collect(repository, config())
    (repository / "app/auth.py").rename(repository / "app/permission.py")
    for name in ("app/checkout.py", "tests/test_auth.py"):
        path = repository / name
        path.write_text(path.read_text().replace(".auth import", ".permission import"))
    (repository / "tests/test_new.py").write_text(
        "from app.permission import allowed\ndef test_new(): assert allowed()\n"
    )
    commit(repository)
    head, _, _ = collect(repository, config())
    result = plan(repository, base, head, policy())
    assert result.mode == "subset"
    assert selected_paths(result, head) == {
        "tests/test_auth.py",
        "tests/test_checkout.py",
        "tests/test_new.py",
    }
    assert "app/auth.py" in base.graph.owners and "app/auth.py" not in head.graph.owners
    assert "app/permission.py" in head.graph.owners
    assert "app/permission.py" in {
        edge.target
        for edge in head.provenance.edges
        if edge.source == "app/checkout.py"
    }


@pytest.mark.parametrize(
    "path,contents,expected",
    [
        ("tests/conftest.py", "\n# shared fixture change\n", "RISK_PATH"),
        ("pytest.ini", "\n# configuration change\n", "ENVIRONMENT_MISMATCH"),
        ("unknown.txt", "unknown relationship", "UNMAPPED_PATH"),
        (
            "app/dynamic.py",
            "import importlib\ndef load(name): return importlib.import_module(name)\n",
            "INCOMPLETE_EVIDENCE",
        ),
    ],
)
def test_fallback_cases_use_full_execution(repository, path, contents, expected):
    base, _, _ = collect(repository, config())
    target = repository / path
    target.write_text((target.read_text() if target.exists() else "") + contents)
    commit(repository)
    head, _, _ = collect(repository, config())
    result = plan(repository, base, head, policy())
    assert result.mode == result.execution == "full"
    assert expected in result.fallback
    if path == "app/dynamic.py":
        assert any("DYNAMIC_IMPORT" in warning for warning in result.warnings)


def test_shared_fixture_dependency_and_resources_broaden_automatically(repository):
    base, _, _ = collect(repository, config())
    (repository / "app/shared.py").write_text(
        "VALUE = 7\n# changed fixture dependency\n"
    )
    commit(repository)
    head, _, _ = collect(repository, config())
    result = plan(repository, base, head, policy())
    assert len(result.selected) == len(head.inventory.tests)
    assert any(
        e.kind == "fixture" and e.target == "tests/conftest.py"
        for e in head.provenance.edges
    )
    assert any(e.kind == "resource" for e in head.provenance.edges)


def test_dirty_symlink_and_ignored_code_cannot_produce_complete_evidence(repository):
    (repository / "untracked.py").write_text("# uncommitted\n")
    with pytest.raises(AdapterError, match="clean"):
        collect(repository, config())
    (repository / "untracked.py").unlink()
    ignored = repository / "ignored"
    ignored.mkdir()
    (ignored / "hidden.py").write_text("# ignored source\n")
    snapshot, _, _ = collect(repository, config())
    assert not snapshot.graph.complete
    assert "UNTRACKED_PYTHON_SOURCE" in {g.code for g in snapshot.provenance.gaps}
    (repository / "linked.py").symlink_to("app/auth.py")
    commit(repository)
    with pytest.raises(AdapterError, match="tree entry"):
        collect(repository, config())


def test_snapshot_integrity_environment_staleness_and_dirty_plan(repository):
    base, _, _ = collect(repository, config())
    broken = base.model_dump()
    broken["graph"]["dependencies"] = {}
    with pytest.raises(ValidationError):
        Snapshot.model_validate(broken)
    incompatible = base.model_dump()
    incompatible["provenance"]["environment"]["distributions"]["pytest"] = "other"
    incompatible["inventory"]["environment"] = Environment.model_validate(
        incompatible["provenance"]["environment"]
    ).identity()
    assert plan(repository, base, resign(incompatible), policy()).fallback == [
        "ENVIRONMENT_MISMATCH"
    ]
    stale = base.model_dump()
    stale["provenance"]["implementation_digest"] = "0" * 64
    assert plan(repository, resign(stale), base, policy()).fallback == [
        "COLLECTOR_VERSION_MISMATCH"
    ]
    (repository / "app/auth.py").write_text("# dirty\n")
    assert plan(repository, base, base, policy()).fallback == [
        "STALE_OR_DIRTY_WORKSPACE"
    ]


def test_unstable_native_collection_is_a_gap(repository, monkeypatch):
    original = Runner.discover
    counter = 0

    def discover(self):
        nonlocal counter
        units = original(self)
        counter += 1
        if counter == 2:
            self.pytest_cases = (*self.pytest_cases, "unexpected")
        return units

    monkeypatch.setattr(Runner, "discover", discover)
    snapshot, _, _ = collect(repository, config())
    assert "UNSTABLE_DISCOVERY" in {g.code for g in snapshot.provenance.gaps}
    assert not snapshot.graph.complete


def test_cli_missing_evidence_is_full_and_outputs_cannot_overwrite_inputs(
    repository, tmp_path, monkeypatch
):
    output = tmp_path / "selection.json"
    audit = tmp_path / "audit.md"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(policy().model_dump_json())
    arguments = [
        "smartci",
        "plan",
        "--repo",
        str(repository),
        "--base-snapshot",
        str(tmp_path / "missing-base"),
        "--head-snapshot",
        str(tmp_path / "missing-head"),
        "--policy",
        str(policy_path),
        "--output",
        str(output),
        "--audit",
        str(audit),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["mode"] == report["execution"] == "full"
    assert report["fallback"] == ["INVALID_OR_UNAVAILABLE_SNAPSHOT"]
    arguments[arguments.index("--output") + 1] = str(policy_path)
    monkeypatch.setattr(sys, "argv", arguments)
    assert main() == 2
    assert json.loads(policy_path.read_text()) == policy().model_dump()


def test_cli_collect_publishes_coherent_bundle_and_preserves_existing_output(
    repository, tmp_path, monkeypatch
):
    configuration = tmp_path / "collector.json"
    configuration.write_text(config().model_dump_json())
    destination = tmp_path / "collected"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "collect",
            "--repo",
            str(repository),
            "--config",
            str(configuration),
            "--output",
            str(destination),
            "--run-full",
        ],
    )
    assert main() == 0
    snapshot = Snapshot.model_validate_json(
        (destination / "snapshot.json").read_bytes()
    )
    assert snapshot.graph.complete
    assert (
        json.loads((destination / "graph.json").read_text())
        == snapshot.graph.model_dump()
    )
    assert (
        json.loads((destination / "inventory.json").read_text())
        == snapshot.inventory.model_dump()
    )
    assert json.loads((destination / "full-run.json").read_text())["status"] == "passed"
    assert len(json.loads((destination / "native-results.json").read_text())) == 4
    before = (destination / "snapshot.json").read_bytes()
    assert main() == 2
    assert (destination / "snapshot.json").read_bytes() == before


def test_cli_rejects_output_inside_checkout_before_running_code(
    repository, tmp_path, monkeypatch
):
    configuration = tmp_path / "collector.json"
    configuration.write_text(config().model_dump_json())

    def forbidden(*args, **kwargs):
        pytest.fail("native discovery must not run after output validation failed")

    monkeypatch.setattr(Runner, "discover", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "collect",
            "--repo",
            str(repository),
            "--config",
            str(configuration),
            "--output",
            str(repository / "evidence"),
        ],
    )
    assert main() == 2
    assert not (repository / "evidence").exists()
