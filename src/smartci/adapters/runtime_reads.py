"""Optional source-open provenance; temporal observations never authorize skips."""

import hashlib
import json
import os
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from types import FrameType

import pytest

from .runtime_observer import STATE as OBSERVER
from .runtime_observer import Observation

MAX_EVENTS = 5_000
MAX_BYTES = 8 * 1024 * 1024
MAX_FRAMES = 24
FAMILIES = frozenset(
    {
        "coverage",
        "pytest_cov",
        "_pytest",
        "importlib",
        "_frozen_importlib",
        "_frozen_importlib_external",
        "inspect",
        "linecache",
        "tokenize",
        "pathlib",
    }
)


class ReadProvenance:
    def __init__(self, observer: Observation, output: Path) -> None:
        self.observer = observer
        self.output = output.resolve()
        if self.output.is_relative_to(observer.root) or self.output.exists():
            raise ValueError("new provenance output outside repository required")
        if self.output == observer.output:
            raise ValueError("provenance and observation outputs must differ")
        self.active = False
        self.confirmed = False
        self.lifecycle = "before_tests"
        self.completed_protocols = 0
        self.events: dict[str, str] = {}
        self.bytes = 0
        self.diagnostics: set[str] = set()
        self.lock = threading.Lock()

    def stack(self, frame: FrameType | None) -> tuple[list[dict[str, object]], bool]:
        result: list[dict[str, object]] = []
        for _ in range(MAX_FRAMES):
            if frame is None:
                return result, False
            path = self.observer.paths.get(os.path.abspath(frame.f_code.co_filename))
            if path is not None:
                entry: dict[str, object] = {
                    "family": "repository",
                    "path": path,
                    "line": frame.f_lineno,
                }
            else:
                module = frame.f_globals.get("__name__")
                family = (
                    module.split(".", 1)[0]
                    if isinstance(module, str) and len(module) <= 256
                    else ""
                )
                entry = {"family": family if family in FAMILIES else "other"}
            if not result or result[-1] != entry:
                result.append(entry)
            frame = frame.f_back
        return result, frame is not None

    def audit(self, event: str, args: tuple[object, ...]) -> None:
        if not self.active:
            return
        if event == "smartci.read-provenance.probe":
            self.confirmed = True
            return
        if event != "open" or not args or not isinstance(args[0], str):
            return
        path = self.observer.paths.get(os.path.abspath(args[0]))
        if path is None:
            return
        try:
            stack, truncated = self.stack(sys._getframe(1))
        except (ValueError, RecursionError):
            self.diagnostics.add("STACK_UNAVAILABLE")
            return
        main = threading.get_ident() == self.observer.main_thread
        record = {
            "path": path,
            "context": self.observer.context if main else "@other-thread",
            "lifecycle": self.lifecycle if main else "other_thread",
            "stack": stack,
            "stack_truncated": truncated,
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(encoded.encode()).hexdigest()
        size = len(encoded.encode())
        with self.lock:
            if key in self.events:
                return
            if len(self.events) >= MAX_EVENTS or self.bytes + size > MAX_BYTES:
                self.diagnostics.add("READ_PROVENANCE_LIMIT_REACHED")
                return
            self.events[key] = encoded
            self.bytes += size

    def start(self) -> None:
        self.active = True
        sys.addaudithook(self.audit)
        sys.audit("smartci.read-provenance.probe")
        if not self.confirmed:
            self.diagnostics.add("READ_AUDIT_HOOK_NOT_CONFIRMED")

    def finish(self) -> None:
        self.active = False
        with self.observer.output.open("rb") as stream:
            observation = stream.read(64 * 1024 * 1024 + 1)
        if len(observation) > 64 * 1024 * 1024:
            raise ValueError("observation exceeds byte limit")
        payload: dict[str, object] = {
            "schema": "smartci.runtime-read-provenance.v1",
            "commit": self.observer.commit,
            "observation_sha256": hashlib.sha256(observation).hexdigest(),
            "tracer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "omission_authorized": False,
            "completed_protocols": self.completed_protocols,
            "diagnostics": sorted(self.diagnostics),
            "events": [json.loads(self.events[k]) for k in sorted(self.events)],
            "limitations": [
                "open attempts, not proof of successful reads or exclusive ownership",
                "fixed module-family labels are observations, not trusted library identity",
                "post-test reads can affect reports and exit status; they are not irrelevant",
                "bounded Python stacks omit native and child-process activity",
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["digest"] = hashlib.sha256(encoded.encode()).hexdigest()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self.output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")


STATE: pytest.StashKey[ReadProvenance] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--smartci-read-provenance", help="New external read trace")


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    output = config.getoption("--smartci-read-provenance")
    if not output:
        return
    observer = config.stash.get(OBSERVER, None)
    if observer is None or not observer.detailed_contexts:
        raise pytest.UsageError("read provenance requires scoped runtime observation")
    try:
        state = ReadProvenance(observer, Path(output))
    except (OSError, ValueError) as exc:
        raise pytest.UsageError("new external provenance output required") from exc
    config.stash[STATE] = state
    state.start()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None]:
    state = item.config.stash.get(STATE, None)
    if state is not None:
        state.lifecycle = "test_protocol"
    try:
        yield
    finally:
        if state is not None:
            state.completed_protocols += 1
            state.lifecycle = (
                "after_tests"
                if state.completed_protocols == state.observer.case_count
                else "between_tests"
            )


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_sessionfinish(session: pytest.Session) -> Generator[None]:
    state = session.config.stash.get(STATE, None)
    if state is not None:
        state.lifecycle = "session_finish"
    try:
        yield
    finally:
        if state is not None:
            state.finish()


def pytest_unconfigure(config: pytest.Config) -> None:
    state = config.stash.get(STATE, None)
    if state is not None:
        state.active = False
