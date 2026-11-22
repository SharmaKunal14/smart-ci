"""Parse Bazel's declared graph without guessing language-level dependencies.

An unconfigured `deps(//...)` query includes all select branches. This parser
keeps implicit, tool, generated-file and non-test rule relationships. It does
not decide the eligible native target universe or prove hermetic runtime IO.
Those are required before a caller can turn impact evidence into execution.
"""

import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass

from smartci.contracts import TestUnit

MAX_XML_BYTES = 64 * 1024 * 1024
MAX_NODES = 100_000
MAX_EDGES = 1_000_000
MAX_WITNESS_DEPTH = 256
LABEL = re.compile(
    r"^(?:@{1,2}[A-Za-z0-9_.+~\-]+)?//[A-Za-z0-9_./+\-]*:[A-Za-z0-9_./+\-]+$"
)


class QueryError(ValueError):
    """Incomplete or unsupported query evidence requires full execution."""


def label(value: str | None) -> str:
    if value is None or len(value) > 1024 or not LABEL.fullmatch(value):
        raise QueryError("unsupported Bazel label")
    package, target = value.split("//", 1)[1].split(":", 1)
    try:
        TestUnit.relative_path(target)
        if package:
            TestUnit.relative_path(package)
    except ValueError as exc:
        raise QueryError("non-normalized Bazel label") from exc
    return value


def source_path(value: str) -> str | None:
    if not value.startswith("//"):
        return None
    package, target = value[2:].split(":", 1)
    return f"{package}/{target}" if package else target


@dataclass(frozen=True)
class QueryGraph:
    dependencies: dict[str, tuple[str, ...]]
    source_owners: dict[str, str]
    rule_classes: dict[str, str]
    rule_tags: dict[str, tuple[str, ...]]

    def affected(self, paths: list[str]) -> dict[str, list[str]]:
        """Return rule -> dependency witness, including affected build-only rules.

        Unknown paths raise instead of yielding a deceptive empty impact set.
        A caller must union base/head evidence and apply risk/profile gates.
        """
        if not paths or len(paths) > MAX_NODES:
            raise QueryError("nonempty bounded change list required")
        reverse: dict[str, list[str]] = {n: [] for n in self.dependencies}
        for consumer, dependencies in sorted(self.dependencies.items()):
            for dependency in dependencies:
                reverse[dependency].append(consumer)
        witnesses: dict[str, list[str]] = {}
        witness_entries = 0
        pending: deque[str] = deque()
        for path in sorted(set(paths)):
            TestUnit.relative_path(path)
            owner = self.source_owners.get(path)
            if owner is None:
                raise QueryError("change is outside declared source evidence")
            witnesses[owner] = [owner]
            witness_entries += 1
            pending.append(owner)
        while pending:
            node = pending.popleft()
            for consumer in reverse[node]:
                if consumer not in witnesses:
                    witness_entries += len(witnesses[node]) + 1
                    if (
                        len(witnesses[node]) >= MAX_WITNESS_DEPTH
                        or witness_entries > MAX_EDGES
                    ):
                        raise QueryError("dependency witnesses exceed bounded limits")
                    witnesses[consumer] = [consumer, *witnesses[node]]
                    pending.append(consumer)
        return {n: witnesses[n] for n in sorted(witnesses) if n in self.rule_classes}


def parse_query_xml(raw: bytes) -> QueryGraph:
    if (
        len(raw) > MAX_XML_BYTES
        or b"\0" in raw
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        raise QueryError("query XML is oversized or contains a forbidden declaration")
    try:
        raw.decode("utf-8")
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError) as exc:
        raise QueryError("invalid query XML") from exc
    if root.tag != "query" or len(root) == 0 or len(root) > MAX_NODES:
        raise QueryError("invalid query root or node count")
    dependencies: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    rules: dict[str, str] = {}
    tags: dict[str, tuple[str, ...]] = {}
    edge_count = 0
    for element in root:
        name = label(element.get("name"))
        if name in dependencies:
            raise QueryError("duplicate query target")
        inputs = set()
        if element.tag == "rule":
            kind = element.get("class", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", kind):
                raise QueryError("invalid rule class")
            rules[name] = kind
            for item in element.findall("rule-input"):
                inputs.add(label(item.get("name")))
            tag_values = []
            for attribute in element.findall("list"):
                if attribute.get("name") == "tags":
                    for item in attribute:
                        value = item.get("value")
                        if item.tag != "string" or value is None or len(value) > 256:
                            raise QueryError("invalid rule tag")
                        tag_values.append(value)
            tags[name] = tuple(sorted(set(tag_values)))
        elif element.tag == "source-file":
            path = source_path(name)
            if path is not None:
                if path in owners:
                    raise QueryError("ambiguous source owner")
                owners[path] = name
        elif element.tag == "generated-file":
            inputs.add(label(element.get("generating-rule")))
        elif element.tag != "package-group":
            raise QueryError("unsupported query target type")
        edge_count += len(inputs)
        if edge_count > MAX_EDGES:
            raise QueryError("query edge count exceeds limit")
        dependencies[name] = tuple(sorted(inputs))
    if any(n not in dependencies for values in dependencies.values() for n in values):
        raise QueryError("query graph is not dependency-closed")
    return QueryGraph(
        dict(sorted(dependencies.items())),
        dict(sorted(owners.items())),
        dict(sorted(rules.items())),
        dict(sorted(tags.items())),
    )
