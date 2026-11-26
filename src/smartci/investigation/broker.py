"""Read only revision-bound Git blobs. Never execute repository code or model text."""

import hashlib
from pathlib import Path

from smartci.git_changes import git
from smartci.selection import Graph, digest

from .adapters import EvidenceAdapter
from .change_scope import compare
from .models import (
    Accepted,
    CompareSource,
    Inputs,
    Inspect,
    Limits,
    Location,
    Observation,
    Propose,
    Query,
    ReadSource,
    Search,
)


class Broker:
    def __init__(
        self,
        root: Path,
        inputs: Inputs,
        adapter: EvidenceAdapter,
        limits: Limits,
        *,
        additional_adapters: tuple[EvidenceAdapter, ...] = (),
    ) -> None:
        self.root = root
        self.inputs = inputs.model_copy(deep=True)
        self.adapter = adapter
        available = (adapter, *additional_adapters)
        self.adapters = {item.name: item for item in available}
        if len(available) > 8 or len(self.adapters) != len(available):
            raise ValueError("invalid or duplicate evidence adapter registration")
        self.limit = limits.source_bytes
        self.bytes_read = 0
        self.observations: dict[str, Observation] = {}

    def capabilities(self) -> list[dict[str, str]]:
        return [
            {"adapter": name, "relation": adapter.relation}
            for name, adapter in sorted(self.adapters.items())
        ]

    def graph(self, revision: str) -> Graph:
        if revision not in self.inputs.sources:
            raise ValueError("revision outside investigation")
        return (
            self.inputs.base
            if revision == self.inputs.base.commit
            else self.inputs.head
        )

    def _read(self, action: Location) -> bytes:
        graph = self.graph(action.revision)
        if action.path not in graph.owners:
            raise ValueError("path outside source catalog")
        obj = f"{action.revision}:{action.path}"
        size = int(git(self.root, "--no-replace-objects", "cat-file", "-s", obj))
        if size > 262_144 or self.bytes_read + size > self.limit:
            raise ValueError("source budget exhausted")
        raw = git(self.root, "--no-replace-objects", "cat-file", "blob", obj)
        if len(raw) != size:
            raise ValueError("source size mismatch")
        self.bytes_read += len(raw)
        source_digest = hashlib.sha256(raw).hexdigest()
        if source_digest != self.inputs.sources[action.revision][action.path]:
            raise ValueError("source digest mismatch")
        return raw

    def read_source(self, action: ReadSource) -> dict[str, object]:
        if not self.inputs.policy.allow_source_excerpts:
            raise ValueError("source excerpts not authorized")
        raw = self._read(action)
        lines = raw.decode("utf-8").splitlines()
        if action.start > len(lines):
            raise ValueError("source line outside file")
        excerpt = "\n".join(lines[action.start - 1 : action.start - 1 + action.lines])
        if len(excerpt.encode()) > 8000:
            raise ValueError("source excerpt exceeds limit")
        return {
            "revision": action.revision,
            "path": action.path,
            "start": action.start,
            "source_digest": self.inputs.sources[action.revision][action.path],
            "excerpt": excerpt,
            "excerpt_digest": digest(excerpt),
        }

    def inspect(self, action: Inspect) -> Observation:
        adapter = self.adapters.get(action.adapter or self.adapter.name)
        if adapter is None:
            raise ValueError("evidence adapter not registered")
        raw = self._read(action)
        graph = self.graph(action.revision)
        source_digest = hashlib.sha256(raw).hexdigest()
        facts = adapter.inspect(action.path, raw, set(graph.owners))
        record = {
            "revision": action.revision,
            "path": action.path,
            "source_digest": source_digest,
            "adapter": adapter.name,
            "adapter_digest": adapter.identity(),
            "facts": [fact.model_dump() for fact in facts[:64]],
            "facts_truncated": len(facts) > 64,
        }
        observation = Observation.model_validate(record | {"evidence": digest(record)})
        self.observations[observation.evidence] = observation
        return observation

    def compare_source(self, action: CompareSource) -> dict[str, object]:
        if action.path not in self.inputs.changes.paths:
            raise ValueError("comparison path not part of recorded change")
        revisions = {"base": self.inputs.base.commit, "head": self.inputs.head.commit}
        # The caller cannot substitute either revision or assert source identity.
        # Added/deleted/unmapped sources are unsupported by this initial tool.
        if any(action.path not in self.graph(r).owners for r in revisions.values()):
            raise ValueError("comparison needs both catalogued source versions")
        raw = {
            side: self._read(Location(revision=revision, path=action.path))
            for side, revision in revisions.items()
        }
        result = compare(action.path, raw["base"], raw["head"]) | {
            "comparison": revisions
        }
        # This report is deliberately not registered as positive edge evidence.
        # It cannot validate a proposal or certify an absence of dependencies.
        return result | {"digest": digest(result)}

    def verify(self, action: Propose) -> Accepted:
        observation = self.observations.get(action.evidence)
        adapter = self.adapters.get(observation.adapter) if observation else None
        if (
            observation is None
            or adapter is None
            or (
                observation.revision != action.revision
                or observation.path != action.path
                or action.relation != adapter.relation
                or observation.adapter_digest != adapter.identity()
                or not any(
                    f.target == action.target and f.line == action.line
                    for f in observation.facts
                )
            )
        ):
            raise ValueError("claim lacks verified matching evidence")
        # Only broker-generated observations can reach here. JSON supplied by the
        # provider cannot create an observation or assert completeness.
        graph = self.graph(action.revision)
        return Accepted(
            **action.model_dump(),
            verifier=adapter.name,
            verifier_digest=observation.adapter_digest,
            source_digest=observation.source_digest,
            already_recorded=graph.owners[action.target]
            in graph.dependencies[graph.owners[action.path]],
        )

    def search(self, action: Search) -> dict[str, object]:
        matches = sorted(
            {
                p
                for g in (self.inputs.base, self.inputs.head)
                for p in g.owners
                if action.query in p
            }
        )
        return {"paths": matches[:64], "truncated": len(matches) > 64}

    def query(self, action: Query) -> dict[str, object]:
        graph = self.graph(action.revision)
        node = graph.owners[action.path]
        owners = {node: path for path, node in graph.owners.items()}
        dependencies = sorted(owners.get(d, d) for d in graph.dependencies[node])
        return {
            "dependencies": dependencies[:64],
            "truncated": len(dependencies) > 64,
            "complete": graph.complete,
        }
