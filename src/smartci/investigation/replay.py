"""A deterministic mock tool chooser. This does not simulate model quality."""

import json

from .models import Location, Observation


class ImportReplay:
    name = "rule-driven-import-replay-v1"

    def __init__(
        self, locations: list[Location], relation: str = "python_absolute_import"
    ) -> None:
        if len(locations) > 16:
            raise ValueError("too many investigation locations")
        self.locations = iter(locations)
        self.pending: list[dict[str, object]] = []
        self.relation = relation

    def next_action(self, context: str) -> str:
        previous = json.loads(context)["previous"]
        if previous and "facts" in previous:
            observation = Observation.model_validate(previous)
            self.pending.extend(
                {
                    "kind": "propose",
                    "revision": observation.revision,
                    "path": observation.path,
                    "target": fact.target,
                    "line": fact.line,
                    "evidence": observation.evidence,
                    "relation": self.relation,
                }
                for fact in observation.facts[:2]
            )
        if self.pending:
            return json.dumps(self.pending.pop(0))
        location = next(self.locations, None)
        return json.dumps(
            {"kind": "finish"}
            if location is None
            else {"kind": "inspect", **location.model_dump()}
        )


class DiagnosticReplay:
    """Offline tool-routing control, not evidence of LLM effectiveness.

    Choose the process inspector for process gaps when trusted registration
    advertises it. Feed observations back into verified positive proposals.
    No diagnostic, including a successful inspection, can clear an unknown.
    """

    name = "rule-driven-diagnostic-replay-v1"

    def __init__(self) -> None:
        self.pending: list[dict[str, object]] = []
        self.locations: list[dict[str, object]] | None = None

    def next_action(self, context: str) -> str:
        data = json.loads(context)
        capabilities = {
            item["adapter"]: item["relation"] for item in data["evidence_adapters"]
        }
        if self.locations is None:
            paths = sorted(
                {
                    issue.split(":", 2)[1]
                    for issue in data["unresolved"]
                    if issue.startswith("DYNAMIC_PROCESS:")
                    and len(issue.split(":", 2)) == 3
                }
            )[:4]
            self.locations = [
                {
                    "kind": "inspect",
                    "adapter": "python-process-script-v1",
                    "revision": revision,
                    "path": path,
                }
                for path in paths
                for revision in sorted(set(data["comparison"].values()))
                if "python-process-script-v1" in capabilities
            ]
        previous = data["previous"]
        if previous and "facts" in previous:
            observation = Observation.model_validate(previous)
            self.pending.extend(
                {
                    "kind": "propose",
                    "revision": observation.revision,
                    "path": observation.path,
                    "target": fact.target,
                    "line": fact.line,
                    "evidence": observation.evidence,
                    "relation": capabilities[observation.adapter],
                }
                for fact in observation.facts[:2]
            )
        if self.pending:
            return json.dumps(self.pending.pop(0))
        return json.dumps(
            self.locations.pop(0) if self.locations else {"kind": "finish"}
        )


class ChangeScopeReplay:
    """Bounded offline scope inspection; no inference or omission authority."""

    name = "rule-driven-change-scope-replay-v1"

    def __init__(self) -> None:
        self.paths: list[str] | None = None

    def next_action(self, context: str) -> str:
        if self.paths is None:
            data = json.loads(context)
            self.paths = sorted(
                {p for p in data["changed_paths"] if p.endswith(".py")}
            )[:4]
        return json.dumps(
            {"kind": "compare_source", "path": self.paths.pop(0)}
            if self.paths
            else {"kind": "finish"}
        )
