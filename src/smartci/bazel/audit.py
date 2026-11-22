"""Reconcile a declared query graph with an independently observed native scope.

This audit grants no execution authority and makes no runtime-hermeticity claim.
In particular, a test rule in a query is not necessarily a natively eligible test.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from smartci.contracts import Digest

from .graph import MAX_NODES, QueryError, QueryGraph, label


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Configuration(_StrictModel):
    id: Digest


class _Completed(_StrictModel):
    label: str
    configuration: _Configuration


class _BuildID(_StrictModel):
    targetCompleted: _Completed


class _Summary(_StrictModel):
    complete_stream: StrictBool
    exit_code: StrictInt
    build_target_configuration_count: int = Field(ge=1, le=MAX_NODES)
    failed_build_target_configuration_count: int = Field(ge=0, le=MAX_NODES)
    build_target_results: dict[str, StrictBool] = Field(max_length=MAX_NODES)
    test_target_count: int = Field(ge=1, le=MAX_NODES)
    test_targets: dict[str, str] = Field(max_length=MAX_NODES)


@dataclass(frozen=True)
class NativeInventory:
    build_configurations: dict[str, tuple[str, ...]]
    tests: tuple[str, ...]

    @property
    def build_only(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.build_configurations) - set(self.tests)))


def native_inventory(summary: object) -> NativeInventory:
    """Consume the complete BEP reconciler's output, retaining build-only scope.

    Provenance/profile validation belongs at the artifact acquisition boundary.
    This function cannot turn arbitrary caller assertions into trusted evidence.
    """
    try:
        parsed = _Summary.model_validate(summary)
        if (
            not parsed.complete_stream
            or parsed.exit_code != 0
            or parsed.failed_build_target_configuration_count != 0
            or len(parsed.build_target_results)
            != parsed.build_target_configuration_count
            or len(parsed.test_targets) != parsed.test_target_count
            or not all(parsed.build_target_results.values())
            or set(parsed.test_targets.values()) != {"PASSED"}
        ):
            raise QueryError("native reference is incomplete or nonpassing")
        configurations: dict[str, set[str]] = {}
        for key in parsed.build_target_results:
            target = _BuildID.model_validate_json(key).targetCompleted
            name = label(target.label)
            if not name.startswith("//"):
                raise QueryError("external native root is unsupported")
            values = configurations.setdefault(name, set())
            if target.configuration.id in values:
                raise QueryError("duplicate native configuration")
            values.add(target.configuration.id)
        tests = tuple(sorted(label(name) for name in parsed.test_targets))
        if not set(tests) <= configurations.keys():
            raise QueryError("native tests are missing build evidence")
        return NativeInventory(
            {name: tuple(sorted(ids)) for name, ids in sorted(configurations.items())},
            tests,
        )
    except ValueError as exc:
        raise QueryError("invalid native reference") from exc


def reconcile_graph(
    graph: QueryGraph, root_labels: list[str], native: NativeInventory
) -> dict[str, object]:
    """Verify actual query roots cover native results without guessing eligibility."""
    if not root_labels or len(root_labels) > MAX_NODES:
        raise QueryError("query root inventory exceeds bounds or is empty")
    roots = {label(value) for value in root_labels}
    if len(roots) != len(root_labels) or not roots <= graph.dependencies.keys():
        raise QueryError("duplicate or missing query root")
    built = set(native.build_configurations)
    if not built <= roots or not built <= graph.rule_classes.keys():
        raise QueryError("native root is missing from query graph")
    test_rules = {n for n in roots if graph.rule_classes.get(n, "").endswith("_test")}
    return {
        "graph_nodes": len(graph.dependencies),
        "graph_edges": sum(map(len, graph.dependencies.values())),
        "source_paths": len(graph.source_owners),
        "query_roots": len(roots),
        "native_build_roots": sorted(built),
        "native_tests": list(native.tests),
        "native_build_only": list(native.build_only),
        "query_test_rules_not_natively_executed": sorted(
            test_rules - set(native.tests)
        ),
        "query_roots_not_natively_built": sorted(roots - built),
        "omission_authorized": False,
    }
