"""GitHub delivery adapter for the same native CLI lifecycle used by other CI."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, model_validator

from .action_control import (
    ARTIFACT_PREFIX,
    BRANCH,
    WORKFLOW,
    Context,
    Invocation,
    publisher_policy,
    read_object,
    revision,
    validate_invocation,
    write,
)
from .bazel.bundle import StrictModel, canonical
from .bazel.collection import CaptureCommand, CaptureConfig, collect
from .bazel.execution import ExecutionConfig
from .bazel.lifecycle import run
from .bazel.transport import Publisher, api, fetch, parse_object


class MapSource(StrictModel):
    branch: str = Field(pattern="^" + BRANCH + "$")
    workflow: str = Field(pattern="^" + WORKFLOW + "$")
    artifact_prefix: str = Field(
        default="smartci-native-map", pattern="^" + ARTIFACT_PREFIX + "$"
    )


class ActionPolicy(StrictModel):
    schema_version: Literal["1"]
    files: list[str] = Field(max_length=64)
    capture: CaptureConfig
    execution: ExecutionConfig
    fallback: CaptureCommand
    publisher: Publisher | None = None
    publisher_capture: CaptureConfig | None = None
    must_run: list[str] = Field(default_factory=list, max_length=10000)
    maps: MapSource | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.maps is not None and (
            self.publisher is not None or self.publisher_capture is not None
        ):
            raise ValueError("automatic maps cannot override an explicit publisher")
        if self.capture.profile != self.execution.profile:
            raise ValueError("capture and execution profiles differ")
        if (self.publisher is None) != (self.publisher_capture is None):
            raise ValueError(
                "publisher identity and capture contract required together"
            )
        if (
            self.publisher is not None
            and self.publisher_capture is not None
            and (
                self.publisher_capture.profile != self.capture.profile
                or self.publisher.repository != self.capture.profile.repository
            )
        ):
            raise ValueError("publisher profile mismatch")
        return self


def load(state: Path) -> tuple[Context, ActionPolicy]:
    value = read_object(state / "context.json")
    if set(value) != {"repository", "repo", "base", "head"}:
        raise ValueError("invalid Action context")
    repo, repository = value["repo"], value["repository"]
    if not isinstance(repo, str) or not isinstance(repository, str):
        raise TypeError("invalid repository identity")
    context: Context = {
        "repository": repository,
        "repo": repo,
        "base": revision(value["base"]),
        "head": revision(value["head"]),
    }
    policy = ActionPolicy.model_validate(read_object(state / "policy.json"))
    if policy.capture.profile.repository != repository:
        raise ValueError("Action configuration belongs to another repository")
    if state.is_relative_to(Path(repo)) or Path(repo).is_relative_to(state):
        raise ValueError("external state directory required")
    return context, policy


def invocation(state: Path) -> Invocation | None:
    path = state / "invocation.json"
    return validate_invocation(read_object(path)) if path.exists() else None


def enrolling(state: Path, context: Context, policy: ActionPolicy) -> bool:
    event = invocation(state)
    if event is None or event["event"] == "pull_request":
        return False
    if (
        policy.maps is None
        or context["base"] != context["head"]
        or event["branch"] != policy.maps.branch
        or event["workflow"] != policy.maps.workflow
    ):
        raise ValueError("unapproved map publication origin")
    return True


def prepare(state: Path) -> None:
    """Validate control-plane inputs and fetch evidence; execute no repository code."""
    context, policy = load(state)
    is_enrollment = enrolling(state, context, policy)
    for name, value in (("capture", policy.capture), ("execution", policy.execution)):
        with (state / f"{name}.json").open("xb") as stream:
            stream.write(canonical(value.model_dump()))
    publisher = policy.publisher
    publisher_capture = policy.publisher_capture
    if policy.maps is not None:
        publisher = Publisher.model_validate(
            publisher_policy(context, policy.maps.model_dump())
        )
        publisher_capture = policy.capture
        write(state / "publisher.json", publisher.model_dump())
    if publisher_capture is not None:
        with (state / "publisher-capture.json").open("xb") as stream:
            stream.write(canonical(publisher_capture.model_dump()))
    if is_enrollment:
        print(
            "Approved branch push; full native enrollment will publish a fresh map.",
            flush=True,
        )
        return
    if publisher is None or publisher_capture is None:
        print(
            "No publisher configured; PR execution will reconstruct or run full.",
            flush=True,
        )
        return
    try:
        pointer = parse_object(
            api(
                f"repos/{publisher.repository}/git/ref/heads/{quote(publisher.branch, safe='')}"
            )
        )
        obj = pointer.get("object")
        if not isinstance(obj, dict) or obj.get("type") != "commit":
            raise ValueError("publisher must reference a commit")
        target = revision(obj.get("sha"))
        fetch(publisher, target, publisher_capture, state / "map")
        print("Retrieved and authenticated the reviewed native map.", flush=True)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        write(
            state / "fetch-error.json",
            {"status": "unavailable", "reason": "MAP_RETRIEVAL_FAILED"},
        )
        print(
            "Map retrieval failed; execution will reconstruct or run full.", flush=True
        )


def execute(state: Path, force_full: bool = False) -> int:
    context, policy = load(state)
    if enrolling(state, context, policy):
        if force_full:
            raise ValueError("force-full is a PR execution option")
        report = collect(
            Path(context["repo"]), context["head"], policy.capture, state / "enrollment"
        )
        if report["status"] != "ready":
            return 1
        write(
            state / "publication.json",
            {
                "schema_version": "smartci.native-action-publication.v1",
                "repository": context["repository"],
                "revision": context["head"],
                "manifest_digest": report["manifest_digest"],
                "config_digest": report["config_digest"],
                "model_calls": 0,
            },
        )
        return 0
    report = run(
        Path(context["repo"]),
        context["base"],
        context["head"],
        state / "map",
        state / "capture.json",
        state / "execution.json",
        state / "native-pr",
        state / "publisher-capture.json"
        if policy.publisher_capture is not None or policy.maps is not None
        else None,
        must_run=tuple(policy.must_run),
        force_full=force_full,
    )
    code = report["exit_code"]
    return (
        code
        if type(code) is int and 0 < code <= 255
        else 0
        if report["status"] == "passed"
        else 1
    )


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "github-action", help="GitHub delivery for the native CLI engine"
    )
    parser.add_argument("operation", choices=["prepare", "execute"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--force-full", action="store_true")


def command(args: argparse.Namespace) -> int:
    try:
        state = args.state.resolve(strict=True)
        if args.operation == "prepare":
            prepare(state)
            return 0
        return execute(state, args.force_full)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print(json.dumps({"status": "error", "code": "NATIVE_ACTION_FAILED"}))
        return 2
