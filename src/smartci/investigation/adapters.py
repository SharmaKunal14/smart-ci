"""Positive evidence adapters, not declarations of dependency completeness."""

import ast
import hashlib
from pathlib import Path
from typing import Protocol

from smartci.contracts import TestUnit
from smartci.selection import digest

from .models import ImportFact


class EvidenceAdapter(Protocol):
    name: str
    relation: str

    def identity(self) -> str: ...

    def inspect(
        self, path: str, source: bytes, catalog: set[str]
    ) -> list[ImportFact]: ...


class PythonImports:
    """Verify explicit absolute import syntax and unambiguous local resolution.

    Conditional imports are retained. Relative/dynamic imports, attribute access,
    resources and process behavior are outside this verifier's capability.
    """

    name = "python-absolute-import-v1"
    relation = "python_absolute_import"

    def __init__(self, roots: list[str]) -> None:
        if not roots or len(roots) > 16 or len(set(roots)) != len(roots):
            raise ValueError("invalid module roots")
        for root in roots:
            if root != ".":
                TestUnit.relative_path(root)
        self.roots = sorted(roots)

    def identity(self) -> str:
        return digest(
            {
                "name": self.name,
                "roots": self.roots,
                "implementation": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            }
        )

    def inspect(self, path: str, source: bytes, catalog: set[str]) -> list[ImportFact]:
        if not path.endswith(".py"):
            raise ValueError("unsupported source language")
        tree = ast.parse(source, filename="<repository-source>")
        facts: set[tuple[str, int]] = set()
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in modules:
                suffix = module.replace(".", "/")
                candidates = {
                    f"{'' if root == '.' else root + '/'}{suffix}{ending}"
                    for root in self.roots
                    for ending in (".py", "/__init__.py")
                } & catalog
                if len(candidates) == 1:
                    facts.add((next(iter(candidates)), node.lineno))
        return [ImportFact(target=target, line=line) for target, line in sorted(facts)]
