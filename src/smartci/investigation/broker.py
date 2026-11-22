"""Read only revision-bound Git blobs. Never execute repository code or model text."""

import hashlib
from pathlib import Path

from smartci.git_changes import git
from smartci.selection import Graph, digest

from .adapters import EvidenceAdapter
from .models import (
    Accepted,
    Inputs,
    Inspect,
    Limits,
    Observation,
    Propose,
    Query,
    Search,
)


class Broker:
    def __init__(
        self, root: Path, inputs: Inputs, adapter: EvidenceAdapter, limits: Limits
    ) -> None:
        self.root = root
        self.inputs = inputs.model_copy(deep=True)
        self.adapter = adapter
        self.limit = limits.source_bytes
        self.bytes_read = 0
        self.observations: dict[str, Observation] = {}

    def graph(self, revision: str) -> Graph:
        if revision not in self.inputs.sources:
            raise ValueError("revision outside investigation")
        return (
            self.inputs.base
            if revision == self.inputs.base.commit
            else self.inputs.head
        )

    def inspect(self, action: Inspect) -> Observation:
        graph = self.graph(action.revision)
        if action.path not in graph.owners:
            raise ValueError("path outside source catalog")
        obj = f"{action.revision}:{action.path}"
        size = int(git(self.root, "cat-file", "-s", obj))
        if size > 262_144 or self.bytes_read + size > self.limit:
            raise ValueError("source budget exhausted")
        raw = git(self.root, "cat-file", "blob", obj)
        if len(raw) != size:
            raise ValueError("source size mismatch")
        self.bytes_read += len(raw)
        source_digest = hashlib.sha256(raw).hexdigest()
        if source_digest != self.inputs.sources[action.revision][action.path]:
            raise ValueError("source digest mismatch")
        facts = self.adapter.inspect(action.path, raw, set(graph.owners))
        record = {
            "revision": action.revision,
            "path": action.path,
            "source_digest": source_digest,
            "adapter": self.adapter.name,
            "adapter_digest": self.adapter.identity(),
            "facts": [fact.model_dump() for fact in facts[:64]],
            "facts_truncated": len(facts) > 64,
        }
        observation = Observation.model_validate(record | {"evidence": digest(record)})
        self.observations[observation.evidence] = observation
        return observation

    def verify(self, action: Propose) -> Accepted:
        observation = self.observations.get(action.evidence)
        if observation is None or (
            observation.revision != action.revision
            or observation.path != action.path
            or action.relation != self.adapter.relation
            or observation.adapter_digest != self.adapter.identity()
            or not any(
                f.target == action.target and f.line == action.line
                for f in observation.facts
            )
        ):
            raise ValueError("claim lacks verified matching evidence")
        # Only broker-generated observations can reach here. JSON supplied by the
        # provider cannot create an observation or assert completeness.
        graph = self.graph(action.revision)
        return Accepted(
            **action.model_dump(),
            verifier=self.adapter.name,
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
