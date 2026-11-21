"""Provider boundary; fixture implementation never accesses the network."""

from typing import Protocol

from .contracts import Investigation, ToolRequest


class Provider(Protocol):
    def next_action(self, request: Investigation) -> ToolRequest: ...


class FixtureProvider:
    def __init__(self, response: ToolRequest) -> None:
        self._response = response.model_copy(deep=True)

    def next_action(self, request: Investigation) -> ToolRequest:
        if request.repository != self._response.repository:
            raise ValueError("repository mismatch")
        return self._response.model_copy(deep=True)
