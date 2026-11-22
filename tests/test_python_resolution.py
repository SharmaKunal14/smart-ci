"""Resolve supported package structure without guessing opaque dependencies."""

from test_discovery import analyse, environment

from smartci.discovery.models import PythonConfig
from smartci.discovery.python_graph import Analysis


def test_namespace_below_regular_package_resolves_before_visiting_imports():
    files = {
        "app/__init__.py": "",
        "app/entry.py": "from app.helpers import utility\n",
        "app/helpers/utility.py": "VALUE = 1\n",
    }
    result = analyse(files)
    assert not result.gaps
    assert "app/helpers/utility.py" in result.dependencies["app/entry.py"]
    assert "app/__init__.py" in result.dependencies["app/helpers/utility.py"]
    repeated = analyse(dict(reversed(list(files.items()))))
    assert repeated.edges == result.edges
    assert repeated.imports == result.imports
    result.files.pop("app/__init__.py")
    result.analyse()
    assert "UNSUPPORTED_NAMESPACE_PACKAGE" in {g.code for g in result.gaps}
    assert not result.namespaces


def test_packaged_test_helper_keeps_namespace_with_separate_source_root():
    files = {
        "src/app/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_render.py": "from tests.utilities.render import render\n",
        "tests/utilities/render.py": "def render(): pass\n",
    }
    config = PythonConfig(
        schema_version="1",
        repository="fixture",
        source_roots=["src"],
        test_roots=["tests"],
    )
    result = Analysis({p: s.encode() for p, s in files.items()}, config, environment())
    result.analyse()
    assert not result.gaps
    assert "tests/utilities/render.py" in result.dependencies["tests/test_render.py"]


def test_extended_package_paths_and_non_package_parents_remain_incomplete():
    extended = analyse(
        {
            "app/__init__.py": "__path__.append('/elsewhere')\n",
            "app/helpers/tool.py": "",
        }
    )
    assert "CUSTOM_IMPORT_PATH" in {g.code for g in extended.gaps}
    collision = analyse({"app.py": "", "app/helpers/tool.py": ""})
    assert "NON_PACKAGE_PARENT" in {g.code for g in collision.gaps}
    root_namespace = analyse({"namespace/module.py": ""})
    assert "UNSUPPORTED_NAMESPACE_PACKAGE" in {g.code for g in root_namespace.gaps}


def test_literal_relative_dynamic_import_preserves_exact_dependency():
    result = analyse(
        {
            "app/__init__.py": "",
            "app/plugin.py": "",
            "app/entry.py": "from importlib import import_module as load\nload('.plugin', package='app')\n",
        }
    )
    assert not result.gaps
    assert "app/plugin.py" in result.dependencies["app/entry.py"]
    for expression in [
        "load(name, package='app')",
        "load('.plugin', package=package)",
        "load('..plugin', package='app')",
    ]:
        opaque = analyse(
            {
                "app/__init__.py": "",
                "app/entry.py": "from importlib import import_module as load\n"
                + expression,
            }
        )
        assert "DYNAMIC_IMPORT" in {g.code for g in opaque.gaps}


def test_closed_lazy_export_retains_import_edges():
    source = """def __getattr__(name):
    if name == "Plugin":
        from .plugin import Plugin
        return Plugin
    raise AttributeError(f"Unknown name {name}")
"""
    result = analyse(
        {"app/__init__.py": source, "app/plugin.py": "class Plugin: pass\n"}
    )
    assert not result.gaps
    assert "app/plugin.py" in result.dependencies["app/__init__.py"]
    for extra in ["    exec(name)\n", "    loader(name)\n", "    name = other\n"]:
        modified = source.replace(
            '    if name == "Plugin":', extra + '    if name == "Plugin":'
        )
        result = analyse({"app/__init__.py": modified, "app/plugin.py": ""})
        assert "DYNAMIC_ATTRIBUTE_HOOK" in {g.code for g in result.gaps}


def test_metadata_only_lazy_attribute_and_changed_dispatch():
    source = """def __getattr__(name):
    if name == "__version__":
        from importlib.metadata import version
        return version("example")
    raise AttributeError(name)
"""
    assert not analyse({"app/__init__.py": source}).gaps
    for modified in [
        source.replace('version("example")', "version(name)"),
        source.replace("from importlib.metadata", "from unknown"),
        source.replace("AttributeError(name)", "AttributeError(load(name))"),
    ]:
        assert "DYNAMIC_ATTRIBUTE_HOOK" in {
            g.code for g in analyse({"app/__init__.py": modified}).gaps
        }


def test_opaque_loader_and_path_mutations_still_force_incomplete_evidence():
    source = """import importlib
import sys
def load(name):
    sys.path.append(name)
    return importlib.import_module(name)
"""
    result = analyse({"app/__init__.py": "", "app/loader.py": source})
    assert {"CUSTOM_IMPORT_PATH", "DYNAMIC_IMPORT"} <= {g.code for g in result.gaps}
