"""Describe a Python edit's syntactic scope without claiming runtime independence.

Body-only edits can still affect decorators, metaclasses, reflection, serialized
code, source reads and other tests. This tool never certifies omission safety.
"""

import ast
import hashlib
import platform
from dataclasses import dataclass
from pathlib import Path

from smartci.contracts import TestUnit
from smartci.selection import digest

MAX_SOURCE = 262_144
MAX_NODES = 20_000
MAX_FUNCTIONS = 256
MAX_CHANGED = 32
NAME = "python-change-scope-v1"


def implementation_digest() -> str:
    return digest(
        {
            "name": NAME,
            "implementation": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "python": platform.python_version(),
        }
    )


def syntax_digest(node: ast.AST) -> str:
    return digest(ast.dump(node, annotate_fields=True, include_attributes=False))


@dataclass(frozen=True)
class Function:
    name: str
    occurrence: int
    entry_line: int
    end_line: int
    body_digest: str
    doc_digest: str
    decorated: bool
    class_member: bool

    def location(self) -> dict[str, object]:
        return {
            "entry_line": self.entry_line,
            "end_line": self.end_line,
            "body_digest": self.body_digest,
        }


def describe(source: bytes) -> tuple[str, str, dict[tuple[str, int], Function]]:
    if len(source) > MAX_SOURCE:
        raise ValueError("source exceeds change inspection limit")
    tree = ast.parse(source, filename="<repository-source>", type_comments=True)
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ValueError("syntax exceeds change inspection limit")
    full = syntax_digest(tree)
    functions: dict[tuple[str, int], Function] = {}
    occurrences: dict[str, int] = {}

    def block(statements: list[ast.stmt], prefix: str = "") -> None:
        for node in statements:
            if isinstance(node, ast.ClassDef):
                block(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(functions) >= MAX_FUNCTIONS:
                    raise ValueError("callable count exceeds inspection limit")
                name = prefix + node.name
                occurrence = occurrences.get(name, 0)
                occurrences[name] = occurrence + 1
                functions[(name, occurrence)] = Function(
                    name=name,
                    occurrence=occurrence,
                    entry_line=min(
                        [node.lineno, *[d.lineno for d in node.decorator_list]]
                    ),
                    end_line=node.end_lineno or node.lineno,
                    body_digest=syntax_digest(
                        ast.Module(body=node.body, type_ignores=[])
                    ),
                    doc_digest=digest(ast.get_docstring(node, clean=False)),
                    decorated=bool(node.decorator_list),
                    class_member=bool(prefix),
                )
                # Retain signatures, annotations, decorators, async/type parameters
                # and statement order. Nested definitions belong to this body.
                # Definitions under control flow remain in the unmasked skeleton.
                node.body = [ast.Pass()]

    block(tree.body)
    return full, syntax_digest(tree), functions


def compare(path: str, before: bytes, after: bytes) -> dict[str, object]:
    TestUnit.relative_path(path)
    if not path.endswith(".py"):
        raise ValueError("change inspection supports Python sources only")
    if max(len(before), len(after)) > MAX_SOURCE:
        raise ValueError("source exceeds change inspection limit")
    record: dict[str, object] = {
        "schema_version": "smartci.python-change-scope.v1",
        "verifier": NAME,
        "verifier_digest": implementation_digest(),
        "path": path,
        "source_digests": {
            "base": hashlib.sha256(before).hexdigest(),
            "head": hashlib.sha256(after).hexdigest(),
        },
        "omission_authorized": False,
        "dependency_completeness_established": False,
        "semantics": "syntactic_change_scope_only",
    }
    try:
        old_full, old_skeleton, old_functions = describe(before)
        new_full, new_skeleton, new_functions = describe(after)
    except (SyntaxError, ValueError, RecursionError, UnicodeError):
        return record | {
            "classification": "unsupported",
            "reason": "PARSE_OR_COMPLEXITY_UNSUPPORTED",
            "changed_callables": [],
            "callables_truncated": False,
        }

    matched = sorted(old_functions.keys() & new_functions.keys())
    changed = [
        key
        for key in matched
        if old_functions[key].body_digest != new_functions[key].body_digest
    ]
    docs_changed = any(
        old_functions[key].doc_digest != new_functions[key].doc_digest
        for key in matched
    )
    if before == after:
        classification = "identical_source"
    elif old_full == new_full:
        classification = "syntax_unchanged"
    elif (
        old_skeleton == new_skeleton
        and old_functions.keys() == new_functions.keys()
        and not docs_changed
        and changed
    ):
        classification = "function_body_only"
    else:
        classification = "module_or_definition_change"

    return record | {
        "classification": classification,
        "reason": "FUNCTION_DOCSTRING_CHANGED" if docs_changed else "AST_COMPARISON",
        "changed_callables": [
            {
                "name": key[0],
                "occurrence": key[1],
                "base": old_functions[key].location(),
                "head": new_functions[key].location(),
                "decorated": old_functions[key].decorated
                or new_functions[key].decorated,
                "class_member": old_functions[key].class_member
                or new_functions[key].class_member,
            }
            for key in changed[:MAX_CHANGED]
        ],
        "callables_truncated": len(changed) > MAX_CHANGED,
    }
