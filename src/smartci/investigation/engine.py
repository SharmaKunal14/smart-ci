"""Bounded advisory loop. Model output has no execution or omission authority."""

import json
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from smartci.selection import Report, digest, fallback, finish, select

from .broker import Broker
from .models import (
    Accepted,
    ActionEnvelope,
    CompareSource,
    Finish,
    Inputs,
    Inspect,
    Limits,
    Propose,
    Query,
    ReadSource,
    Search,
    Unresolved,
)


class Provider(Protocol):
    name: str

    def next_action(self, context: str) -> str: ...


@runtime_checkable
class Accounting(Protocol):
    def accounting(self) -> dict[str, object]: ...


def _apply_evidence(
    inputs: Inputs, accepted: list[Accepted]
) -> tuple[Report, dict[str, object]]:
    base, head = inputs.base.model_copy(deep=True), inputs.head.model_copy(deep=True)
    for edge in accepted:
        graph = base if edge.revision == base.commit else head
        source, target = graph.owners[edge.path], graph.owners[edge.target]
        graph.dependencies[source] = sorted(set(graph.dependencies[source]) | {target})
    # Completeness, unknowns, test ownership, mandatory rules and old edges are
    # retained. These graphs can only add may-depend relationships.
    result = select(inputs.changes, inputs.inventory, base, head, inputs.policy)
    version: dict[str, object] = {
        "schema_version": "smartci.accepted-graph.v1",
        "input_digest": inputs.identity(),
        "base": base.model_dump(),
        "head": head.model_dump(),
        "evidence": [
            e.model_dump()
            for e in sorted(
                accepted, key=lambda e: (e.revision, e.path, e.target, e.line)
            )
        ],
        "promotion": "additions_only_no_completeness_authority",
    }
    return result, version | {"digest": digest(version)}


def investigate(
    inputs: Inputs,
    broker: Broker,
    provider: Provider,
    limits: Limits,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    # Validate copies at the API boundary, including possibly mutated model instances.
    inputs = Inputs.model_validate_json(inputs.model_dump_json())
    if broker.inputs != inputs:
        raise ValueError("broker input mismatch")
    baseline = select(
        inputs.changes, inputs.inventory, inputs.base, inputs.head, inputs.policy
    )
    started = clock()
    accepted: list[Accepted] = []
    unresolved = set(inputs.unresolved)
    trace: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    seen: set[str] = set()
    response_bytes = 0
    status = "step_limit"
    for step in range(limits.steps):
        if clock() - started >= limits.seconds:
            status = "deadline"
            break
        context = json.dumps(
            {
                "step": step,
                "repository": inputs.changes.repository,
                "comparison": {"base": inputs.base.commit, "head": inputs.head.commit},
                "changed_paths": inputs.changes.paths[:64],
                "unresolved_count": len(unresolved),
                "unresolved": sorted(unresolved)[:32],
                "unresolved_truncated": len(unresolved) > 32,
                "previous": previous,
                "remaining_steps": limits.steps - step,
                "authority": "propose_additions_only",
                "evidence_adapters": broker.capabilities(),
            },
            sort_keys=True,
        )
        try:
            try:
                raw = provider.next_action(context)
            except (RuntimeError, ValueError, OSError, StopIteration):
                # Provider transport/runtime failures must retain full execution;
                # raw exception text may contain prompts or credentials.
                status = "provider_error"
                break
            if not isinstance(raw, str) or len(raw.encode()) > 8192:
                raise ValueError("provider response exceeds limit")
            response_bytes += len(raw.encode())
            if (
                response_bytes > limits.response_bytes
                or clock() - started >= limits.seconds
            ):
                status = "budget_exhausted"
                break
            action = ActionEnvelope.model_validate_json(raw).root
            identity = digest(action.model_dump())
            if identity in seen:
                status = "duplicate_action"
                break
            seen.add(identity)
            result: dict[str, object]
            if isinstance(action, Finish):
                result = {"status": "finished"}
                status = "finished"
            elif isinstance(action, Inspect):
                result = broker.inspect(action).model_dump()
            elif isinstance(action, ReadSource):
                result = broker.read_source(action)
            elif isinstance(action, CompareSource):
                result = broker.compare_source(action)
            elif isinstance(action, Search):
                result = broker.search(action)
            elif isinstance(action, Query):
                result = broker.query(action)
            elif isinstance(action, Propose):
                edge = broker.verify(action)
                accepted.append(edge)
                result = {"accepted": edge.model_dump()}
            elif isinstance(action, Unresolved):
                label = "PROVIDER_UNRESOLVED:" + digest(action.label)
                unresolved.add(label)
                result = {"unresolved": label}
            encoded_size = len(json.dumps(result).encode())
            response_bytes += encoded_size
            if response_bytes > limits.response_bytes:
                status = "budget_exhausted"
                break
            trace.append(
                {
                    "action_digest": identity,
                    "kind": action.kind,
                    "result": {k: v for k, v in result.items() if k != "excerpt"},
                }
            )
            previous = result
            if status == "finished":
                break
        except (ValueError, OSError, KeyError, TypeError, RecursionError, SyntaxError):
            # Never log arbitrary provider text, source content, or exception values.
            status = "invalid_action_or_evidence"
            break
    final, graph = _apply_evidence(inputs, accepted)
    if status != "finished" or unresolved:
        final = fallback("INVESTIGATION_INCOMPLETE", inputs.inventory)
    if baseline.execution == "full":
        # Preserve the native independent full command and original fallback causes.
        final = baseline.model_copy(deep=True)
    elif not set(baseline.selected) <= set(final.selected):
        final = fallback("INVESTIGATION_MONOTONICITY_FAILURE", inputs.inventory)
    final.comparison = baseline.comparison
    final.evidence.update(
        {"baseline": baseline.digest, "accepted_graph": str(graph["digest"])}
    )
    final = finish(final)
    accounting = (
        provider.accounting()
        if isinstance(provider, Accounting)
        else {"evaluation_kind": "offline_plumbing_only", "model_calls": 0}
    )
    report = {
        "schema_version": "smartci.investigation-report.v1",
        "provider": provider.name,
        "evaluation_kind": accounting["evaluation_kind"],
        "model_calls": accounting["model_calls"],
        "accounting": accounting,
        "model_effectiveness_measured": False,
        "input_digest": inputs.identity(),
        "status": status,
        "limits": limits.model_dump(),
        "steps": len(trace),
        "source_bytes": broker.bytes_read,
        "response_bytes": response_bytes,
        "trace": trace,
        "unresolved": sorted(unresolved),
        "accepted_graph": graph,
        "baseline": baseline.model_dump(),
        "final": final.model_dump(),
    }
    return report | {"digest": digest(report)}
