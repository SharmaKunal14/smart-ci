"""Bounded native Build Event Protocol reconciliation for portable evidence.

The old example baseline keeps its standalone reader for existing copied CI
harnesses. Shared tests verify both readers; new reusable adapters use this module.
"""

import io
import json
import re
from pathlib import Path
from typing import BinaryIO

MAX_BEP_BYTES = 64 * 1024 * 1024


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate build-event JSON key")
        result[key] = value
    return result


def event_key(value: object) -> str:
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("invalid build-event ID")
    key = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(key) > 4096:
        # A selective target-pattern event repeats the complete exclusion list.
        # Keep ordinary IDs small; admit only this bounded, explicit native form.
        pattern = value.get("pattern")
        values = pattern.get("pattern") if isinstance(pattern, dict) else None
        if (
            len(key) > 64 * 1024
            or not isinstance(pattern, dict)
            or set(pattern) != {"pattern"}
            or not isinstance(values, list)
            or not 2 <= len(values) <= 2048
            or values[0] != "..."
            or any(
                not isinstance(item, str)
                or len(item) > 1024
                or not re.fullmatch(r"-//[A-Za-z0-9_./+\-]*:[A-Za-z0-9_./+\-]+", item)
                for item in values[1:]
            )
            or len(set(values)) != len(values)
        ):
            raise ValueError("build-event ID exceeds supported bounds")
    return key


def summarize_stream(stream: BinaryIO) -> dict[str, object]:
    """Require the announced native event graph, not just a success marker.

    This remains single-profile baseline evidence. It neither establishes a
    complete source dependency graph nor authorizes future test omissions.
    """
    summaries: dict[str, str] = {}
    received: set[str] = set()
    announced: set[str] = set()
    expected_tests: set[str] = set()
    actual_tests: set[str] = set()
    build_results: dict[str, bool] = {}
    finished: int | None = None
    last_message = False
    total = 0
    while line := stream.readline(8 * 1024 * 1024 + 1):
        total += len(line)
        if total > MAX_BEP_BYTES or len(line) > 8 * 1024 * 1024:
            raise ValueError("build events exceed limit")
        if last_message:
            raise ValueError("events after terminal build message")
        event = json.loads(line, object_pairs_hook=unique_object)
        if not isinstance(event, dict):
            raise TypeError("invalid build event")
        identifier = event["id"]
        key = event_key(identifier)
        if key in received or len(received) >= 100_000:
            raise ValueError("duplicate or excessive build events")
        if not received and (
            identifier != {"started": {}}
            or event.get("started", {}).get("command") != "test"
        ):
            raise ValueError("native test build start required")
        received.add(key)
        children = event.get("children", [])
        if not isinstance(children, list):
            raise TypeError("invalid build-event children")
        for child in children:
            child_key = event_key(child)
            announced.add(child_key)
            if len(announced) > 100_000:
                raise ValueError("excessive announced build events")
            if "testSummary" in child:
                expected_tests.add(child_key)
        if "aborted" in event:
            raise ValueError("aborted native build evidence")
        if "testSummary" in event:
            label = identifier["testSummary"]["label"]
            status = event["testSummary"]["overallStatus"]
            if (
                not isinstance(label, str)
                or not label.startswith("//")
                or label in summaries
                or status
                not in {
                    "PASSED",
                    "FLAKY",
                    "TIMEOUT",
                    "FAILED",
                    "INCOMPLETE",
                    "REMOTE_FAILURE",
                    "FAILED_TO_BUILD",
                    "TOOL_HALTED_BEFORE_TESTING",
                }
            ):
                raise ValueError("invalid or duplicate test summary")
            summaries[label] = status
            actual_tests.add(key)
        if "targetCompleted" in identifier:
            success = event["completed"].get("success", False)
            if type(success) is not bool:
                raise ValueError("invalid native build result")
            build_results[key] = success
        if "finished" in event:
            if finished is not None or identifier != {"buildFinished": {}}:
                raise ValueError("duplicate build completion")
            exit_code = event["finished"]["exitCode"]
            finished = exit_code.get("code")
            if finished is None and exit_code.get("name") == "SUCCESS":
                finished = 0
            if type(finished) is not int or not 0 <= finished <= 255:
                raise ValueError("invalid build exit code")
        last_message = event.get("lastMessage") is True
    if (
        finished is None
        or not last_message
        # Compilation may fail before any test starts. Only a native build
        # failure with completed failed targets can explain zero summaries;
        # announced-but-missing summaries still fail the closure checks below.
        or (not summaries and (finished != 1 or all(build_results.values())))
        or not build_results
        or received != announced | {event_key({"started": {}})}
        or actual_tests != expected_tests
    ):
        raise ValueError("incomplete native build evidence")
    if finished == 0 and (
        not all(build_results.values())
        or any(status not in {"PASSED", "FLAKY"} for status in summaries.values())
    ):
        raise ValueError("contradictory native success evidence")
    return {
        "complete_stream": True,
        "exit_code": finished,
        "build_target_configuration_count": len(build_results),
        "failed_build_target_configuration_count": sum(
            not success for success in build_results.values()
        ),
        "build_target_results": dict(sorted(build_results.items())),
        "test_target_count": len(summaries),
        "test_targets": dict(sorted(summaries.items())),
    }


def summarize_events(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        return summarize_stream(stream)


def summarize_bytes(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_BEP_BYTES:
        raise ValueError("build events exceed limit")
    return summarize_stream(io.BytesIO(raw))
