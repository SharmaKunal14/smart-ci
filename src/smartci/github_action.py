"""GitHub delivery adapter for the same native CLI lifecycle used by other CI."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, model_validator

from .action_control import Context, read_object, revision, write
from .bazel.bundle import StrictModel, canonical
from .bazel.collection import CaptureCommand, CaptureConfig
from .bazel.execution import ExecutionConfig
from .bazel.lifecycle import run
from .bazel.transport import Publisher, api, fetch, parse_object


class ActionPolicy(StrictModel):
    schema_version: Literal["1"]
    files: list[str] = Field(max_length=64)
    capture: CaptureConfig
    execution: ExecutionConfig
    fallback: CaptureCommand
    publisher: Publisher | None = None
    publisher_capture: CaptureConfig | None = None
    must_run: list[str] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def consistent(self) -> Self:
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


def prepare(state: Path) -> None:
    """Validate control-plane inputs and fetch evidence; execute no repository code."""
    _, policy = load(state)
    for name, value in (("capture", policy.capture), ("execution", policy.execution)):
        with (state / f"{name}.json").open("xb") as stream:
            stream.write(canonical(value.model_dump()))
    if policy.publisher_capture is not None:
        with (state / "publisher-capture.json").open("xb") as stream:
            stream.write(canonical(policy.publisher_capture.model_dump()))
    if policy.publisher is None or policy.publisher_capture is None:
        print(
            "No publisher configured; PR execution will reconstruct or run full.",
            flush=True,
        )
        return
    try:
        publisher = policy.publisher
        pointer = parse_object(
            api(
                f"repos/{publisher.repository}/git/ref/heads/{quote(publisher.branch, safe='')}"
            )
        )
        obj = pointer.get("object")
        if not isinstance(obj, dict) or obj.get("type") != "commit":
            raise ValueError("publisher must reference a commit")
        target = revision(obj.get("sha"))
        fetch(publisher, target, policy.publisher_capture, state / "map")
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
    report = run(
        Path(context["repo"]),
        context["base"],
        context["head"],
        state / "map",
        state / "capture.json",
        state / "execution.json",
        state / "native-pr",
        state / "publisher-capture.json"
        if policy.publisher_capture is not None
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
