"""Conservative file-level Python import resolution. No application imports here."""

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from smartci.selection import digest

from .models import Edge, Environment, Gap, ImportFact, PythonConfig


def inside(path: str, root: str) -> bool:
    return root == "." or path == root or path.startswith(root + "/")


def node_id(path: str) -> str:
    return "file:" + digest(path)


def module_name(path: str, config: PythonConfig, paths: set[str]) -> str:
    roots = [r for r in config.source_roots if inside(path, r)]
    if roots:
        root = max(roots, key=len)
        relative = path if root == "." else path[len(root) + 1 :]
    else:
        relative = path
        # pytest's default prepend mode imports unpackaged test files by basename.
        parent = PurePosixPath(path).parent
        if (parent / "__init__.py").as_posix() not in paths:
            relative = PurePosixPath(path).name
    parts = relative.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass
class Analysis:
    files: dict[str, bytes]
    config: PythonConfig
    environment: Environment
    dependencies: dict[str, set[str]] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    trees: dict[str, ast.Module] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    imports: list[ImportFact] = field(default_factory=list)

    def gap(self, code: str, path: str, line: int = 0) -> None:
        self.gaps.append(Gap(code=code, path=path, line=line))

    def edge(self, source: str, target: str, kind: str, line: int = 0) -> None:
        if source == target:
            return
        if len(self.edges) >= 1_000_000:
            raise ValueError("dependency evidence exceeds limit")
        self.dependencies[source].add(target)
        self.edges.append(
            Edge.model_validate(
                {"source": source, "target": target, "kind": kind, "line": line}
            )
        )

    def analyse(self) -> None:
        self.dependencies = {p: set() for p in self.files}
        for path, raw in sorted(self.files.items()):
            if not path.endswith(".py"):
                continue
            name = module_name(path, self.config, set(self.files))
            self.names[path] = name
            if not name or not all(p.isidentifier() for p in name.split(".")):
                self.gap("UNSUPPORTED_MODULE_NAME", path)
            if name in self.modules:
                self.gap("AMBIGUOUS_MODULE", path)
            self.modules[name] = path
            try:
                self.trees[path] = ast.parse(raw, filename=path)
            except (SyntaxError, ValueError, RecursionError):
                self.gap("PARSE_ERROR", path)
        for path, tree in sorted(self.trees.items()):
            name = self.names[path]
            for count in range(1, len(name.split("."))):
                parent = ".".join(name.split(".")[:count])
                initializer = self.modules.get(parent)
                if initializer is None:
                    self.gap("UNSUPPORTED_NAMESPACE_PACKAGE", path)
                else:
                    self.edge(path, initializer, "package_init")
            ImportVisitor(self, path).visit(tree)

    def resolve(self, path: str, name: str, line: int, optional: bool = False) -> None:
        top = name.split(".")[0]
        resolution = "unresolved"
        if name in self.modules:
            resolution = "local"
            parts = name.split(".")
            for count in range(1, len(parts) + 1):
                target = self.modules.get(".".join(parts[:count]))
                if target is not None:
                    self.edge(path, target, "import", line)
        elif top in {n.split(".")[0] for n in self.modules}:
            self.gap("UNRESOLVED_LOCAL_IMPORT", path, line)
        elif top in self.environment.stdlib:
            resolution = "stdlib"
        elif top in self.environment.external_modules:
            resolution = "distribution"
        elif optional and top not in self.environment.available_modules:
            resolution = "optional_absent"
        else:
            self.gap("UNRESOLVED_IMPORT", path, line)
        self.imports.append(
            ImportFact.model_validate(
                {"path": path, "line": line, "module": name, "resolution": resolution}
            )
        )

    def shared_inputs(self, test_paths: set[str]) -> None:
        fixtures = {p for p in self.files if PurePosixPath(p).name == "conftest.py"}
        resources = {p for p in self.files if not p.endswith(".py")}
        for path in sorted(test_paths):
            if path not in self.files:
                self.gap("TEST_OUTSIDE_COLLECTED_SCOPE", path)
                continue
            for fixture in sorted(fixtures):
                parent = PurePosixPath(fixture).parent.as_posix()
                if inside(path, parent):
                    self.edge(path, fixture, "fixture")
            # Reading arbitrary resources cannot be inferred from Python imports.
            # All tracked data in enrolled roots is a conservative shared input.
            for resource in sorted(resources):
                self.edge(path, resource, "resource")


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, analysis: Analysis, path: str):
        self.analysis = analysis
        self.path = path
        self.optional = False
        self.aliases: dict[str, str] = {}
        self.constants: dict[str, str] = {}
        self.handled: set[int] = set()

    @staticmethod
    def literal_bindings(node: ast.AST) -> dict[str, str]:
        literal_targets = {}
        for item in ast.walk(node):
            if (
                isinstance(item, ast.Assign)
                and isinstance(item.value, ast.Constant)
                and isinstance(item.value.value, str)
            ):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        literal_targets[id(target)] = item.value.value
        definitions: dict[str, list[str | None]] = {}
        for item in ast.walk(node):
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                definitions.setdefault(item.id, []).append(
                    literal_targets.get(id(item))
                )
            elif isinstance(item, ast.arg):
                definitions.setdefault(item.arg, []).append(None)
        return {
            name: values[0]
            for name, values in definitions.items()
            if len(values) == 1 and values[0] is not None
        }

    def visit_Module(self, node: ast.Module) -> None:
        self.constants = self.literal_bindings(node)
        self.generic_visit(node)

    def qualified(self, expression: ast.expr) -> str:
        if isinstance(expression, ast.Name):
            return self.aliases.get(expression.id, expression.id)
        if isinstance(expression, ast.Attribute):
            return self.qualified(expression.value) + "." + expression.attr
        return ""

    def visit_Import(self, node: ast.Import) -> None:
        for name in node.names:
            self.analysis.resolve(self.path, name.name, node.lineno, self.optional)
            self.aliases[name.asname or name.name.split(".")[0]] = (
                name.name if name.asname else name.name.split(".")[0]
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        name = node.module or ""
        if node.level:
            package = self.analysis.names[self.path].split(".")
            if PurePosixPath(self.path).name != "__init__.py":
                package.pop()
            if node.level > len(package):
                self.analysis.gap(
                    "RELATIVE_IMPORT_OUTSIDE_PACKAGE", self.path, node.lineno
                )
                return
            prefix = package[: len(package) - node.level + 1]
            name = ".".join([*prefix, *([name] if name else [])])
        self.analysis.resolve(self.path, name, node.lineno, self.optional)
        for item in node.names:
            candidate = f"{name}.{item.name}"
            if candidate in self.analysis.modules:
                self.analysis.resolve(self.path, candidate, node.lineno, self.optional)
            self.aliases[item.asname or item.name] = candidate

    def visit_Try(self, node: ast.Try) -> None:
        before = self.optional
        catches_import = any(
            isinstance(part, ast.Name)
            and part.id in {"ImportError", "ModuleNotFoundError"}
            for handler in node.handlers
            if handler.type is not None
            for part in ast.walk(handler.type)
        )
        self.optional = before or catches_import
        for statement in node.body:
            self.visit(statement)
        self.optional = before
        for remaining in [*node.handlers, *node.orelse, *node.finalbody]:
            self.visit(remaining)

    def condition(self, node: ast.expr) -> bool | None:
        if self.qualified(node) == "typing.TYPE_CHECKING":
            return False
        if (
            isinstance(node, ast.Compare)
            and self.qualified(node.left) == "sys.version_info"
            and len(node.ops) == len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Tuple)
        ):
            parts = node.comparators[0].elts
            if len(parts) == 2 and all(
                isinstance(p, ast.Constant) and type(p.value) is int for p in parts
            ):
                version = tuple(
                    map(int, self.analysis.environment.python.split(".")[:2])
                )
                expected = tuple(
                    p.value
                    for p in parts
                    if isinstance(p, ast.Constant) and isinstance(p.value, int)
                )
                if isinstance(node.ops[0], ast.GtE):
                    return version >= expected
                if isinstance(node.ops[0], ast.Lt):
                    return version < expected
        return None

    def visit_If(self, node: ast.If) -> None:
        condition = self.condition(node.test)
        self.visit(node.test)
        before = self.optional
        # Keep both branches' local edges; only explain absent external modules.
        self.optional = before or condition is False
        for statement in node.body:
            self.visit(statement)
        self.optional = before or condition is True
        for statement in node.orelse:
            self.visit(statement)
        self.optional = before

    def visit_Call(self, node: ast.Call) -> None:
        call = self.qualified(node.func)
        if call in {"__import__", "builtins.__import__", "importlib.import_module"}:
            self.handled.add(id(node.func))
            if (
                len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value
                and not node.args[0].value.startswith(".")
            ):
                self.analysis.resolve(
                    self.path, node.args[0].value, node.lineno, self.optional
                )
            else:
                self.analysis.gap("DYNAMIC_IMPORT", self.path, node.lineno)
        elif call in {
            "exec",
            "eval",
            "builtins.exec",
            "builtins.eval",
            "importlib.util.spec_from_file_location",
            "importlib.util.module_from_spec",
            "runpy.run_path",
            "runpy.run_module",
            "globals",
            "locals",
        }:
            self.analysis.gap("DYNAMIC_CODE", self.path, node.lineno)
        if (
            call in {"getattr", "builtins.getattr"}
            and node.args
            and self.qualified(node.args[0]) in {"importlib", "builtins"}
        ):
            self.analysis.gap("DYNAMIC_IMPORT", self.path, node.lineno)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "setitem"
            and len(node.args) >= 2
            and self.qualified(node.args[0]) == "sys.modules"
        ):
            key = node.args[1]
            name = (
                key.value
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
                else self.constants.get(key.id)
                if isinstance(key, ast.Name)
                else None
            )
            local = {n.split(".")[0] for n in self.analysis.modules}
            env = self.analysis.environment
            if (
                name is not None
                and name in self.analysis.config.external_module_overrides
                and name not in local
                and (
                    name in env.stdlib
                    or name in env.external_modules
                    or name not in env.available_modules
                )
            ):
                self.handled.add(id(node.args[0]))
                self.analysis.imports.append(
                    ImportFact(
                        path=self.path,
                        line=node.lineno,
                        module=name,
                        resolution="reviewed_external_override",
                    )
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self.qualified(node) in {"sys.path", "sys.meta_path", "sys.path_hooks"}:
            self.analysis.gap("CUSTOM_IMPORT_PATH", self.path, node.lineno)
        if self.qualified(node) == "sys.modules" and id(node) not in self.handled:
            self.analysis.gap("CUSTOM_MODULE_REGISTRY", self.path, node.lineno)
        if (
            self.qualified(node) in {"importlib.import_module", "builtins.__import__"}
            and id(node) not in self.handled
        ):
            self.analysis.gap("DYNAMIC_IMPORT", self.path, node.lineno)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "__getattr__":
            self.analysis.gap("DYNAMIC_ATTRIBUTE_HOOK", self.path, node.lineno)
        before = self.constants
        self.constants = self.literal_bindings(node)
        self.generic_visit(node)
        self.constants = before

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "pytest_plugins" and isinstance(node.ctx, ast.Store):
            self.analysis.gap("LOCAL_PYTEST_PLUGIN", self.path, node.lineno)
        if (
            isinstance(node.ctx, ast.Load)
            and self.qualified(node)
            in {"__import__", "builtins.__import__", "importlib.import_module"}
            and id(node) not in self.handled
        ):
            self.analysis.gap("DYNAMIC_IMPORT", self.path, node.lineno)
