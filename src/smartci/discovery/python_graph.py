"""Conservative file-level Python import resolution. No application imports here."""

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from smartci.selection import digest

from .attribute_hooks import rejecting_attribute_hook
from .models import Edge, Environment, Gap, ImportFact, PythonConfig

PROCESS_APIS = {
    f"{module}.{name}"
    for module, names in {
        "subprocess": (
            "Popen",
            "run",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
        ),
        "os": (
            "system",
            "popen",
            "fork",
            "forkpty",
            "posix_spawn",
            "posix_spawnp",
            "execl",
            "execle",
            "execlp",
            "execlpe",
            "execv",
            "execve",
            "execvp",
            "execvpe",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "startfile",
        ),
        "asyncio": ("create_subprocess_exec", "create_subprocess_shell"),
        "asyncio.subprocess": ("create_subprocess_exec", "create_subprocess_shell"),
        "multiprocessing": ("Process", "Pool", "Manager", "get_context"),
        "multiprocessing.pool": ("Pool",),
        "concurrent.futures": ("ProcessPoolExecutor",),
        "concurrent.futures.process": ("ProcessPoolExecutor",),
        "pty": ("spawn", "fork"),
    }.items()
    for name in names
}
PROCESS_MODULES = {name.rsplit(".", 1)[0] for name in PROCESS_APIS}


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
        # Helpers below a regular package retain that package's namespace even
        # when an intermediate directory has no initializer. Truly unpackaged
        # test files use pytest's default prepend-mode basename.
        parent = PurePosixPath(path).parent
        if not any(
            (directory / "__init__.py").as_posix() in paths
            for directory in (parent, *parent.parents)
            if directory.as_posix() != "."
        ):
            relative = PurePosixPath(path).name
    parts = relative.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def static_attribute_hook(node: ast.FunctionDef) -> bool:
    """Recognize a closed lazy export table, not arbitrary attribute dispatch.

    Every successful branch imports a literal module and returns its named
    export (or a literal importlib.metadata.version query). The normal visitor
    still records every import. Anything beyond this grammar stays opaque.
    """
    args = node.args
    if (
        node.decorator_list
        or args.posonlyargs
        or len(args.args) != 1
        or args.kwonlyargs
        or args.vararg
        or args.kwarg
        or args.defaults
    ):
        return False
    argument = args.args[0].arg
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    ):
        body.pop(0)
    if len(body) < 2 or not isinstance(body[-1], ast.Raise):
        return False
    exc = body[-1].exc
    if not (
        isinstance(exc, ast.Call)
        and isinstance(exc.func, ast.Name)
        and exc.func.id == "AttributeError"
        and not exc.keywords
        and body[-1].cause is None
    ):
        return False
    # Diagnostics may interpolate the requested name, but cannot run code.
    if any(
        not isinstance(
            part, (ast.Constant, ast.Name, ast.Load, ast.JoinedStr, ast.FormattedValue)
        )
        for arg in exc.args
        for part in ast.walk(arg)
    ):
        return False
    for branch in body[:-1]:
        if not isinstance(branch, ast.If) or branch.orelse:
            return False
        condition = branch.test
        if not (
            isinstance(condition, ast.Compare)
            and isinstance(condition.left, ast.Name)
            and condition.left.id == argument
            and len(condition.ops) == 1
            and isinstance(condition.ops[0], ast.Eq)
            and len(condition.comparators) == 1
            and isinstance(condition.comparators[0], ast.Constant)
            and isinstance(condition.comparators[0].value, str)
            and len(branch.body) == 2
            and isinstance(branch.body[0], ast.ImportFrom)
            and isinstance(branch.body[1], ast.Return)
        ):
            return False
        imported = branch.body[0]
        if len(imported.names) != 1 or imported.names[0].name == "*":
            return False
        alias = imported.names[0]
        result = branch.body[1].value
        if isinstance(result, ast.Name) and result.id == (alias.asname or alias.name):
            continue
        if not (
            imported.module == "importlib.metadata"
            and imported.level == 0
            and alias.name == "version"
            and isinstance(result, ast.Call)
            and isinstance(result.func, ast.Name)
            and result.func.id == (alias.asname or alias.name)
            and len(result.args) == 1
            and isinstance(result.args[0], ast.Constant)
            and isinstance(result.args[0].value, str)
            and not result.keywords
        ):
            return False
    return True


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
    namespaces: set[str] = field(default_factory=set)

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
        self.modules.clear()
        self.names.clear()
        self.trees.clear()
        self.gaps.clear()
        self.edges.clear()
        self.imports.clear()
        self.namespaces.clear()
        self.dependencies = {p: set() for p in self.files}
        paths = set(self.files)
        for path, raw in sorted(self.files.items()):
            if not path.endswith(".py"):
                continue
            name = module_name(path, self.config, paths)
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
                    # A namespace nested under a regular tracked package cannot
                    # acquire portions from unrelated sys.path entries. Root
                    # namespaces still require native search-location evidence.
                    ancestors = [
                        self.modules.get(".".join(name.split(".")[:i]))
                        for i in range(1, count)
                    ]
                    if any(p and p.endswith("/__init__.py") for p in ancestors):
                        self.namespaces.add(parent)
                    else:
                        self.gap("UNSUPPORTED_NAMESPACE_PACKAGE", path)
                elif not initializer.endswith("/__init__.py"):
                    self.gap("NON_PACKAGE_PARENT", path)
                else:
                    self.edge(path, initializer, "package_init")
        for path, tree in sorted(self.trees.items()):
            ImportVisitor(self, path).visit(tree)

    def resolve(self, path: str, name: str, line: int, optional: bool = False) -> None:
        top = name.split(".")[0]
        resolution = "unresolved"
        if name in self.modules or name in self.namespaces:
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
        if name in PROCESS_MODULES and any(item.name == "*" for item in node.names):
            self.analysis.gap("DYNAMIC_PROCESS", self.path, node.lineno)
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
        if call in PROCESS_APIS:
            # Executable, script, shell, worker and environment inputs are not
            # represented by Python imports. No process adapter exists yet.
            self.handled.add(id(node.func))
            self.analysis.gap("DYNAMIC_PROCESS", self.path, node.lineno)
        if (
            node.args
            and self.qualified(node.args[0]) in PROCESS_MODULES
            and (
                call in {"vars", "builtins.vars"}
                or call in {"getattr", "builtins.getattr"}
                and len(node.args) >= 2
                and (
                    not isinstance(node.args[1], ast.Constant)
                    or not isinstance(node.args[1].value, str)
                    or f"{self.qualified(node.args[0])}.{node.args[1].value}"
                    in PROCESS_APIS
                )
            )
        ):
            self.analysis.gap("DYNAMIC_PROCESS", self.path, node.lineno)
        if call in {"__import__", "builtins.__import__", "importlib.import_module"}:
            self.handled.add(id(node.func))
            module = None
            if (
                len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value
                and not node.args[0].value.startswith(".")
            ):
                module = node.args[0].value
            elif (
                call == "importlib.import_module"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith(".")
                and len(node.keywords) == 1
                and node.keywords[0].arg == "package"
                and isinstance(node.keywords[0].value, ast.Constant)
                and isinstance(node.keywords[0].value.value, str)
            ):
                relative = node.args[0].value
                package = node.keywords[0].value.value.split(".")
                level = len(relative) - len(relative.lstrip("."))
                if level <= len(package) and all(p.isidentifier() for p in package):
                    suffix = relative[level:]
                    module = ".".join(
                        package[: len(package) - level + 1]
                        + ([suffix] if suffix else [])
                    )
            if module is not None:
                self.analysis.resolve(self.path, module, node.lineno, self.optional)
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
        if (
            self.qualified(node) in PROCESS_APIS
            and id(node) not in self.handled
            or node.attr == "__dict__"
            and self.qualified(node.value) in PROCESS_MODULES
        ):
            self.analysis.gap("DYNAMIC_PROCESS", self.path, node.lineno)
        if self.qualified(node) in {"sys.path", "sys.meta_path", "sys.path_hooks"}:
            self.analysis.gap("CUSTOM_IMPORT_PATH", self.path, node.lineno)
        if node.attr == "__path__":
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
        if (
            node.name == "__getattr__"
            and not static_attribute_hook(node)
            and not rejecting_attribute_hook(node, self.analysis.trees[self.path])
        ):
            self.analysis.gap("DYNAMIC_ATTRIBUTE_HOOK", self.path, node.lineno)
        before = self.constants
        self.constants = self.literal_bindings(node)
        self.generic_visit(node)
        self.constants = before

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == "__getattr__":
            self.analysis.gap("DYNAMIC_ATTRIBUTE_HOOK", self.path, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and self.qualified(node) in PROCESS_APIS
            and id(node) not in self.handled
        ):
            self.analysis.gap("DYNAMIC_PROCESS", self.path, node.lineno)
        if node.id == "__path__":
            self.analysis.gap("CUSTOM_IMPORT_PATH", self.path, node.lineno)
        if node.id == "pytest_plugins" and isinstance(node.ctx, ast.Store):
            self.analysis.gap("LOCAL_PYTEST_PLUGIN", self.path, node.lineno)
        if (
            isinstance(node.ctx, ast.Load)
            and self.qualified(node)
            in {"__import__", "builtins.__import__", "importlib.import_module"}
            and id(node) not in self.handled
        ):
            self.analysis.gap("DYNAMIC_IMPORT", self.path, node.lineno)
