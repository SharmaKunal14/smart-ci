"""Find file-anchored Python script arguments without executing repository code.

These are structural may-depend facts, never a complete process model. Shell
startup, environment, runtime rebinding, child imports and side effects remain
unresolved. Only straight-line bindings and a bounded argv/pipeline grammar are
recognized. No shell command is executed and no filesystem path is resolved.
"""

import ast
import hashlib
import posixpath
import shlex
from dataclasses import dataclass
from pathlib import Path

from smartci.contracts import TestUnit
from smartci.selection import digest

from .models import ImportFact

MAX_NODES = 20_000
MARKER = "SMARTCI_ARGUMENT_"
PROCESS_CALLS = {
    f"subprocess.{name}"
    for name in ("run", "Popen", "call", "check_call", "check_output")
}
PYTHON_FLAGS = {"-B", "-E", "-I", "-s", "-S", "-u"}


@dataclass(frozen=True)
class ScriptPath:
    path: str


type Bindings = dict[str, str | ScriptPath]


def symbol(node: ast.AST, bindings: Bindings) -> str | None:
    if isinstance(node, ast.Name):
        value = bindings.get(node.id)
        return value if isinstance(value, str) else None
    if isinstance(node, ast.Attribute) and (parent := symbol(node.value, bindings)):
        return parent + "." + node.attr
    return None


def literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def normalized(path: str) -> ScriptPath | None:
    path = posixpath.normpath(path)
    try:
        TestUnit.relative_path(path)
    except ValueError:
        return None
    return ScriptPath(path)


def path_value(node: ast.AST, bindings: Bindings) -> ScriptPath | None:
    if isinstance(node, ast.Name):
        value = bindings.get(node.id)
        return value if isinstance(value, ScriptPath) else None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        parent = path_value(node.value, bindings)
        return normalized(posixpath.dirname(parent.path)) if parent else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = path_value(node.left, bindings), literal(node.right)
        if left and right and not right.startswith("/") and "\\" not in right:
            return normalized(posixpath.join(left.path, right))
    if not isinstance(node, ast.Call) or node.keywords:
        return None
    if symbol(node.func, bindings) == "pathlib.Path" and len(node.args) == 1:
        return path_value(node.args[0], bindings)
    if not isinstance(node.func, ast.Attribute):
        return None
    parent = path_value(node.func.value, bindings)
    if parent and node.func.attr in {"absolute", "resolve"} and not node.args:
        return parent
    if parent and node.func.attr == "with_name" and len(node.args) == 1:
        name = literal(node.args[0])
        if name and "/" not in name and "\\" not in name and name not in {".", ".."}:
            return normalized(posixpath.join(posixpath.dirname(parent.path), name))
    return None


def script_argument(tokens: list[str], paths: dict[str, str]) -> str | None:
    if not tokens or tokens[0] != MARKER + "PYTHON":
        return None
    index = 1
    while index < len(tokens) and tokens[index] in PYTHON_FLAGS:
        index += 1
    return paths.get(tokens[index]) if index < len(tokens) else None


def process_argument(call: ast.Call, bindings: Bindings) -> str | None:
    if symbol(call.func, bindings) not in PROCESS_CALLS or len(call.args) != 1:
        return None
    options = {item.arg: item.value for item in call.keywords}
    if None in options or len(options) != len(call.keywords):
        return None
    paths: dict[str, str] = {}

    def token(node: ast.AST) -> str | None:
        if symbol(node, bindings) == "sys.executable":
            return MARKER + "PYTHON"
        if path := path_value(node, bindings):
            marker = MARKER + str(len(paths))
            paths[marker] = path.path
            return marker
        return None

    argument = call.args[0]
    shell = options.get("shell")
    if isinstance(argument, (ast.List, ast.Tuple)):
        if shell is not None and not (
            isinstance(shell, ast.Constant) and shell.value is False
        ):
            return None
        words = []
        for item in argument.elts:
            value = literal(item)
            if value is not None and MARKER in value:
                return None
            value = value if value is not None else token(item)
            if value is None:
                return None
            words.append(value)
        return script_argument(words, paths)
    if not (
        isinstance(argument, ast.JoinedStr)
        and isinstance(shell, ast.Constant)
        and shell.value is True
    ):
        return None
    chunks = []
    for item in argument.values:
        value = literal(item)
        if value is not None:
            if MARKER in value or any(c in value for c in "$;&<>`\n\r\\#"):
                return None
        elif (
            isinstance(item, ast.FormattedValue)
            and item.conversion == -1
            and item.format_spec is None
        ):
            value = token(item.value)
        if value is None:
            return None
        chunks.append(value)
    command = "".join(chunks)
    # POSIX shlex discards quotes, which would make a literal "|" look like a
    # pipeline operator. Reject that unsupported form before losing provenance.
    quoted = shlex.shlex(command, posix=False, punctuation_chars="|")
    quoted.whitespace_split, quoted.commenters = True, ""
    raw_words = list(quoted)
    if len(raw_words) > 128 or any("|" in word and word != "|" for word in raw_words):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
    lexer.whitespace_split, lexer.commenters = True, ""
    words = list(lexer)
    if len(words) > 128 or any("|" in word and word != "|" for word in words):
        return None
    # Only the last command in a simple pipeline is recognized. Earlier commands
    # are deliberately not interpreted or declared harmless.
    last_pipe = max((i for i, word in enumerate(words) if word == "|"), default=-1)
    return script_argument(words[last_pipe + 1 :], paths)


def assigned_names(node: ast.AST) -> set[str]:
    return (
        {
            item.id
            for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))
        }
        | {
            name
            for item in ast.walk(node)
            if isinstance(item, (ast.Global, ast.Nonlocal))
            for name in item.names
        }
        | {
            alias.asname or alias.name.split(".")[0]
            for item in ast.walk(node)
            if isinstance(item, (ast.Import, ast.ImportFrom))
            for alias in item.names
        }
        | {
            item.name
            for item in ast.walk(node)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        | {
            item.value.id
            for item in ast.walk(node)
            if isinstance(item, (ast.Attribute, ast.Subscript))
            and isinstance(item.ctx, (ast.Store, ast.Del))
            and isinstance(item.value, ast.Name)
        }
    )


class PythonProcessScripts:
    name = "python-process-script-v1"
    relation = "python_process_script_argument"

    def identity(self) -> str:
        return digest(
            {
                "name": self.name,
                "implementation": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            }
        )

    def inspect(self, path: str, source: bytes, catalog: set[str]) -> list[ImportFact]:
        TestUnit.relative_path(path)
        if not path.endswith(".py"):
            raise ValueError("unsupported source language")
        tree = ast.parse(source, filename="<repository-source>")
        if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
            raise ValueError("process syntax exceeds inspection limit")
        facts: set[tuple[str, int]] = set()

        def block(statements: list[ast.stmt], bindings: Bindings) -> None:
            for statement in statements:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    local = bindings.copy()
                    names = assigned_names(statement) | {
                        item.arg
                        for item in ast.walk(statement.args)
                        if isinstance(item, ast.arg)
                    }
                    for name in names:
                        local.pop(name, None)
                    block(statement.body, local)
                    bindings.pop(statement.name, None)
                    continue
                if isinstance(statement, ast.Import):
                    for alias in statement.names:
                        name = alias.asname or alias.name.split(".")[0]
                        bindings.pop(name, None)
                        if alias.name in {"subprocess", "sys", "pathlib"}:
                            bindings[name] = alias.name
                    continue
                if isinstance(statement, ast.ImportFrom):
                    if any(alias.name == "*" for alias in statement.names):
                        bindings.clear()
                        continue
                    for alias in statement.names:
                        name = alias.asname or alias.name
                        bindings.pop(name, None)
                        if statement.level == 0 and statement.module in {
                            "subprocess",
                            "sys",
                            "pathlib",
                        }:
                            bindings[name] = statement.module + "." + alias.name
                    continue
                # Reject control-flow inference rather than guessing which binding
                # reaches a call. Ordinary call/assignment expressions are enough
                # to expose positive evidence; opaque scopes still require fallback.
                if not isinstance(
                    statement, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return)
                ):
                    for name in assigned_names(statement):
                        bindings.pop(name, None)
                    continue
                nodes = list(ast.walk(statement))
                if any(
                    isinstance(item, (ast.Lambda, ast.comprehension, ast.NamedExpr))
                    for item in nodes
                ):
                    for name in assigned_names(statement):
                        bindings.pop(name, None)
                    continue
                for node in nodes:
                    if isinstance(node, ast.Call):
                        target = process_argument(node, bindings)
                        if (
                            target in catalog
                            and target is not None
                            and target.endswith(".py")
                        ):
                            facts.add((target, node.lineno))
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    value = (
                        path_value(statement.value, bindings)
                        if statement.value
                        else None
                    )
                    for name in assigned_names(statement):
                        bindings.pop(name, None)
                    if len(targets) == 1 and isinstance(targets[0], ast.Name) and value:
                        bindings[targets[0].id] = value

        block(tree.body, {"__file__": ScriptPath(path)})
        return [ImportFact(target=target, line=line) for target, line in sorted(facts)]
