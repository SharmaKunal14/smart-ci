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
