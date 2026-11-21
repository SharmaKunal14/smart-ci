"""Collect clean Git snapshots and preserve the target's native pytest settings."""

import ast
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from smartci.adapters.runners import AdapterError, Runner, Unit, invoke, read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.contracts import Inventory, TestUnit
from smartci.git_changes import git
from smartci.selection import Graph, digest

from .models import Environment, Gap, Provenance, PythonConfig, Snapshot
from .python_graph import Analysis, inside, module_name, node_id

MAX_SOURCE_BYTES = 64 * 1024 * 1024
CONFIG_NAMES = {
    "pyproject.toml",
    "pytest.ini",
    ".pytest.ini",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "noxfile.py",
}
AMBIENT_KEYS = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTHONHASHSEED",
    "LANG",
    "LC_ALL",
    "TZ",
)
DEFAULT_HOOKS = {
    "_frozen_importlib.BuiltinImporter",
    "_frozen_importlib.FrozenImporter",
    "_frozen_importlib_external.PathFinder",
}


def implementation_digest() -> str:
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            p.relative_to(root).as_posix(): hashlib.sha256(read_bounded(p)).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


def tracked_files(root: Path, commit: str) -> list[str]:
    paths = []
    for entry in git(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        if metadata.split(b" ", 1)[0] not in {b"100644", b"100755"}:
            raise AdapterError("unsupported Git tree entry")
        path = raw_path.decode("utf-8", errors="strict")
        TestUnit.relative_path(path)
        paths.append(path)
    if len(paths) > 100_000:
        raise AdapterError("repository exceeds collector limit")
    return sorted(paths)


def read_sources(
    root: Path, paths: list[str], config: PythonConfig
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    known_paths = set(paths)
    for path in paths:
        in_tests = any(inside(path, scope) for scope in config.test_roots)
        in_sources = any(inside(path, scope) for scope in config.source_roots)
        package_data = any(
            (parent / "__init__.py").as_posix() in known_paths
            for parent in Path(path).parents
            if parent.as_posix() != "."
        )
        if not (
            in_tests
            or in_sources
            and (path.endswith(".py") or package_data)
            or Path(path).name == "conftest.py"
        ):
            continue
        source = root / path
        if source.resolve(strict=True) != source or not source.is_file():
            raise AdapterError("source path is not a contained regular file")
        raw = read_bounded(source)
        total += len(raw)
        if total > MAX_SOURCE_BYTES:
            raise AdapterError("source inputs exceed collector limit")
        files[path] = raw
    return files


def configuration(root: Path, paths: list[str]) -> dict[str, str]:
    return {
        path: hashlib.sha256(read_bounded(root / path)).hexdigest()
        for path in paths
        if Path(path).name in CONFIG_NAMES
        or Path(path).name.startswith("requirements")
        or path.endswith(".lock")
    }


def probe_names(files: dict[str, bytes], config: PythonConfig) -> list[str]:
    names = set()
    for path, raw in files.items():
        if not path.endswith(".py"):
            continue
        names.add(module_name(path, config, set(files)).split(".")[0])
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError, RecursionError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
            elif (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                # Include literal dynamic imports in the availability probe. No code runs.
                names.add(node.args[0].value.split(".")[0])
    result = sorted(n for n in names if n.isidentifier())
    if len(result) > 1000 or sum(map(len, result)) > 32_000:
        raise AdapterError("module probe exceeds limit")
    return result


def environment(
    root: Path, python: str, names: list[str], configs: dict[str, str]
) -> Environment:
    with tempfile.TemporaryDirectory(prefix="smartci-environment-") as temporary:
        output = Path(temporary) / "environment.json"
        code = invoke(
            [
                python,
                "-I",
                str(Path(__file__).with_name("environment_probe.py")),
                str(root),
                json.dumps(names),
                str(output),
            ],
            root,
            timeout=30,
        )
        if code:
            raise AdapterError("target environment probe failed")
        result = Environment.model_validate_json(read_bounded(output))
    result.ambient = {key: digest(os.environ.get(key)) for key in AMBIENT_KEYS}
    result.configuration = configs
    return result


def environment_gaps(analysis: Analysis, runner: Runner) -> list[Gap]:
    env = analysis.environment
    gaps = []
    if env.python.split(".")[:2] != list(map(str, sys.version_info[:2])):
        gaps.append(Gap(code="PARSER_INTERPRETER_MISMATCH"))
    if not DEFAULT_HOOKS <= set(env.import_hooks) or set(
        env.import_hooks
    ) - DEFAULT_HOOKS - {"_virtualenv._Finder"}:
        gaps.append(Gap(code="CUSTOM_IMPORT_HOOK"))
    if any(os.environ.get(k) for k in AMBIENT_KEYS[:5]):
        gaps.append(Gap(code="AMBIENT_PYTEST_CONFIGURATION"))
    if set(runner.pytest_plugins) - set(analysis.config.allowed_plugins):
        gaps.append(Gap(code="UNREVIEWED_PYTEST_PLUGIN"))
    observer = Path(__file__).parents[1] / "adapters" / "pytest_plugin.py"
    if env.observer_digest != hashlib.sha256(read_bounded(observer)).hexdigest():
        gaps.append(Gap(code="OBSERVER_VERSION_MISMATCH"))
    for name, path in sorted(env.native_roots.items()):
        if path is not None and path not in analysis.files:
            gaps.append(Gap(code="LOCAL_IMPORT_OUTSIDE_SCOPE", path=path))
    for name, path in sorted(analysis.modules.items()):
        if (
            "." not in name
            and any(inside(path, r) for r in analysis.config.source_roots)
            and env.native_roots.get(name) != path
        ):
            gaps.append(Gap(code="NATIVE_IMPORT_ORIGIN_MISMATCH", path=path))
    return gaps


def collect(
    root: Path, config: PythonConfig, python: str | None = None
) -> tuple[Snapshot, Runner, list[Unit]]:
    root = root.resolve(strict=True)
    python = python or sys.executable
    if (
        Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        != root
    ):
        raise AdapterError("repository root required")
    commit = current_clean_head(root)
    if commit is None:
        raise AdapterError("clean committed checkout required")
    for scope in [*config.source_roots, *config.test_roots]:
        folder = root / scope
        if not folder.is_dir() or not folder.resolve().is_relative_to(root):
            raise AdapterError("invalid source or test root")
    paths = tracked_files(root, commit)
    files = read_sources(root, paths, config)
    configs = configuration(root, paths)
    env = environment(root, python, probe_names(files, config), configs)
    runner = Runner(
        "pytest",
        root,
        config.repository,
        python=python,
        native_pytest=True,
        pytest_granularity=config.granularity,
    )
    units = runner.discover()
    initial_cases = runner.pytest_cases
    repeated = runner.discover()
    gaps = []
    if units != repeated or initial_cases != runner.pytest_cases:
        gaps.append(Gap(code="UNSTABLE_DISCOVERY"))
    units = repeated
    if any(
        u.path not in files or not any(inside(u.path, r) for r in config.test_roots)
        for u in units
    ):
        raise AdapterError("native tests outside enrolled roots")
    analysis = Analysis(files, config, env)
    analysis.analyse()
    analysis.shared_inputs({u.path for u in units})
    gaps.extend(analysis.gaps)
    gaps.extend(environment_gaps(analysis, runner))
    ignored = git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        "*.py",
    )
    for path in ignored.decode("utf-8", errors="strict").split("\0"):
        if path and any(
            inside(path, scope) for scope in [*config.source_roots, *config.test_roots]
        ):
            gaps.append(Gap(code="UNTRACKED_PYTHON_SOURCE", path=path))
    if (
        current_clean_head(root) != commit
        or read_sources(root, paths, config) != files
        or configuration(root, paths) != configs
    ):
        raise AdapterError("inputs changed during collection")
    tests = [
        TestUnit(id=u.id, runner="pytest", granularity=config.granularity, path=u.path)
        for u in units
    ]
    inventory = Inventory(
        schema_version="1",
        repository=config.repository,
        complete=True,
        environment=env.identity(),
        tests=tests,
    )
    graph = Graph(
        schema_version="1",
        repository=config.repository,
        commit=commit,
        complete=not gaps,
        unsupported=bool(gaps),
        owners={p: node_id(p) for p in sorted(files)},
        dependencies={
            node_id(p): sorted(node_id(d) for d in deps)
            for p, deps in sorted(analysis.dependencies.items())
        },
        tests={u.id: node_id(u.path) for u in units},
    )
    provenance = Provenance(
        implementation_digest=implementation_digest(),
        config=config,
        environment=env,
        sources={
            p: hashlib.sha256(raw).hexdigest() for p, raw in sorted(files.items())
        },
        edges=sorted(
            analysis.edges, key=lambda e: (e.source, e.target, e.kind, e.line)
        ),
        imports=sorted(
            analysis.imports, key=lambda i: (i.path, i.line, i.module, i.resolution)
        ),
        gaps=sorted(
            {g.model_dump_json(): g for g in gaps}.values(),
            key=lambda g: (g.code, g.path or "", g.line),
        ),
        native_targets={u.id: u.target for u in units},
        native_cases_digest=digest(runner.pytest_cases),
        native_case_count=len(runner.pytest_cases),
        plugins=list(runner.pytest_plugins),
    )
    data = {
        "schema_version": "1",
        "repository": config.repository,
        "inventory": inventory.model_dump(),
        "graph": graph.model_dump(),
        "provenance": provenance.model_dump(),
    }
    return Snapshot.model_validate({**data, "digest": digest(data)}), runner, units
