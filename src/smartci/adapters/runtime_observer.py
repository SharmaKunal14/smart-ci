"""Opt-in, advisory pytest observation. Never authorizes test omissions.

Only tracked repository paths and import *names* are persisted. Audit events
are attempts, not proof of successful reads/imports. Call attribution is temporal:
background asyncio work can outlive a test. Other threads/processes are not
covered by the main-thread profiler. These limitations are unconditional.
"""

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import CodeType, FrameType
from typing import Literal, Protocol

import pytest

SHARED = "@shared"
OTHER_THREAD = "@other-thread"
LIMIT = 500_000


class PathNode(Protocol):
    path: Path


def git(root: Path, *args: str) -> bytes:
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
        output.seek(0)
        data = output.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("repository metadata exceeds observation limit")
        return data


class Observation:
    def __init__(
        self,
        root: Path,
        output: Path,
        limit: int = LIMIT,
        *,
        engine: Literal["profile", "monitoring"] = "profile",
        detailed_contexts: bool = False,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.output = output.resolve()
        if self.output.is_relative_to(self.root) or self.output.exists():
            raise ValueError("new report outside repository required")
        self.commit = git(self.root, "rev-parse", "HEAD").decode().strip()
        git(self.root, "diff", "--quiet", "HEAD")
        self.paths: dict[str, str] = {}
        self.blobs: dict[str, str] = {}
        for item in git(self.root, "ls-tree", "-rz", "HEAD").split(b"\0"):
            if not item:
                continue
            metadata, raw_path = item.split(b"\t", 1)
            mode, _, blob = metadata.decode().split()
            path = raw_path.decode()
            if mode not in {"100644", "100755"}:
                raise ValueError("non-regular Git entries are not supported")
            self.paths[str(self.root / path)] = path
            self.blobs[path] = blob
        if len(self.paths) > 100_000:
            raise ValueError("repository file count exceeds observation limit")
        self.main_thread = threading.get_ident()
        self.context = SHARED
        self.active = False
        self.contexts: dict[str, dict[str, set[str]]] = {}
        self.diagnostics: set[str] = set()
        self.count = 0
        self.limit = limit
        self.test_files: set[str] = set()
        self.case_count = 0
        self.audit_confirmed = False
        self.filename_cache: dict[str, str | None] = {}
        self.profile_installed = False
        self.engine = engine
        self.detailed_contexts = detailed_contexts
        self.monitoring_id: int | None = None
        self.monitoring_name = f"smartci-observation-{id(self)}"
        self.context_metadata: dict[str, dict[str, str]] = {}

    @contextmanager
    def phase(self, kind: str, scope: str, owner: str) -> Generator[None]:
        """Record temporal scope, never a proof of exclusive dependency ownership.

        No fixture is evaluated, wrapped, requested or finalized by this observer.
        Session/package fixtures are attributed to their scope, not their first
        consumer. Teardown stays shared because public hooks do not surround each
        cached fixture finalizer.
        """
        if not self.detailed_contexts:
            yield
            return
        previous = self.context
        metadata = {"kind": kind, "scope": scope, "owner": owner}
        key = (
            "@phase:"
            + hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        )
        if len(self.context_metadata) >= 100_000 and key not in self.context_metadata:
            self.diagnostics.add("CONTEXT_LIMIT_REACHED")
            self.context = SHARED
        else:
            self.context_metadata[key] = metadata
            self.context = key
        try:
            yield
        finally:
            self.context = previous

    def node_owner(self, node: PathNode, scope: str) -> str:
        """Keep parameter values and external paths out of observation metadata."""
        if scope == "session":
            return "."
        try:
            owner = node.path.resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            self.diagnostics.add("UNTRACKED_SCOPE_OWNER")
            return "@unknown"
        if (
            owner in self.blobs
            or scope == "package"
            and (owner == "." or any(p.startswith(owner + "/") for p in self.blobs))
        ):
            return owner
        self.diagnostics.add("UNTRACKED_SCOPE_OWNER")
        return "@unknown"

    def add(self, kind: str, value: str) -> None:
        if not self.active:
            return
        if self.count >= self.limit:
            self.diagnostics.add("OBSERVATION_LIMIT_REACHED")
            return
        context = (
            self.context if threading.get_ident() == self.main_thread else OTHER_THREAD
        )
        entries = self.contexts.setdefault(context, {}).setdefault(kind, set())
        if value not in entries:
            entries.add(value)
            self.count += 1

    def profile(self, frame: FrameType, event: str, arg: object) -> None:
        if not self.active or event != "call":
            return
        self.record_code(frame.f_code)

    def monitor(self, code: CodeType, offset: int) -> None:
        if self.active:
            self.record_code(code)

    def monitor_throw(self, code: CodeType, offset: int, error: BaseException) -> None:
        if self.active:
            self.record_code(code)

    def record_code(self, code: CodeType) -> None:
        filename = code.co_filename
        # Profile filenames are normally absolute. Do not cache relative paths:
        # a test can change cwd between executions of the same code object.
        if filename in self.filename_cache:
            path = self.filename_cache[filename]
        elif os.path.isabs(filename):
            if filename not in self.filename_cache:
                if len(self.filename_cache) >= 100_000:
                    self.diagnostics.add("FILENAME_CACHE_LIMIT_REACHED")
                    return
                self.filename_cache[filename] = self.paths.get(filename)
            path = self.filename_cache[filename]
        else:
            path = self.paths.get(os.path.abspath(filename))
        if path is not None:
            self.add("code_files", path)
            self.add("code_entries", f"{path}:{code.co_firstlineno}")

    def audit(self, event: str, args: tuple[object, ...]) -> None:
        if not self.active:
            return
        if event == "smartci.observation.probe":
            self.audit_confirmed = True
        elif event == "open" and args and isinstance(args[0], str):
            path = self.paths.get(os.path.abspath(args[0]))
            if path is not None:
                self.add("open_attempts", path)
            else:
                self.diagnostics.add("UNTRACKED_OR_EXTERNAL_OPENS_NOT_ATTRIBUTED")
        elif event == "import" and args and isinstance(args[0], str):
            name = args[0]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,255}", name):
                self.add("import_requests", name)
        elif event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}:
            self.diagnostics.add("CHILD_PROCESS_NOT_OBSERVED")
            # Retain the temporal caller without persisting executable/arguments.
            # This is not observation of the child or proof of exclusive ownership.
            self.add("process_events", "CHILD_PROCESS_ATTEMPT")

    def start(self) -> None:
        self.active = True
        sys.addaudithook(self.audit)
        sys.audit("smartci.observation.probe")
        if not self.audit_confirmed:
            self.diagnostics.add("AUDIT_HOOK_NOT_CONFIRMED")
        if self.engine == "monitoring":
            self.start_monitoring()
        elif sys.getprofile() is None:
            sys.setprofile(self.profile)
            self.profile_installed = True
        else:
            self.diagnostics.add("EXISTING_PROFILER_NOT_REPLACED")

    def start_monitoring(self) -> None:
        # Reserve only unclaimed, non-conventional IDs. Do not restart events:
        # restart_events affects other tools too, including native coverage.
        for tool_id in (3, 4):
            try:
                sys.monitoring.use_tool_id(tool_id, self.monitoring_name)
            except ValueError:
                continue
            self.monitoring_id = tool_id
            events = sys.monitoring.events
            sys.monitoring.register_callback(tool_id, events.PY_START, self.monitor)
            sys.monitoring.register_callback(tool_id, events.PY_RESUME, self.monitor)
            sys.monitoring.register_callback(
                tool_id, events.PY_THROW, self.monitor_throw
            )
            sys.monitoring.set_events(
                tool_id, events.PY_START | events.PY_RESUME | events.PY_THROW
            )
            return
        self.diagnostics.add("NO_MONITORING_TOOL_ID_AVAILABLE")

    def stop(self) -> None:
        self.active = False
        if self.monitoring_id is not None:
            tool_id = self.monitoring_id
            if sys.monitoring.get_tool(tool_id) == self.monitoring_name:
                sys.monitoring.set_events(tool_id, 0)
                for event in (
                    sys.monitoring.events.PY_START,
                    sys.monitoring.events.PY_RESUME,
                    sys.monitoring.events.PY_THROW,
                ):
                    sys.monitoring.register_callback(tool_id, event, None)
                sys.monitoring.free_tool_id(tool_id)
            else:
                self.diagnostics.add("MONITORING_TOOL_REPLACED_DURING_RUN")
            self.monitoring_id = None
        if self.profile_installed:
            if sys.getprofile() == self.profile:
                sys.setprofile(None)
            else:
                self.diagnostics.add("PROFILER_REPLACED_DURING_RUN")
            self.profile_installed = False

    def test_context(self, item: pytest.Item) -> str:
        path = item.nodeid.split("::", 1)[0]
        if path not in self.blobs:
            self.diagnostics.add("UNTRACKED_TEST_CONTEXT")
            return SHARED
        return path

    def finish(self, exitstatus: int, plugins: list[str]) -> None:
        self.stop()
        try:
            git(self.root, "diff", "--quiet", "HEAD")
            if git(self.root, "rev-parse", "HEAD").decode().strip() != self.commit:
                self.diagnostics.add("REVISION_CHANGED_DURING_RUN")
        except (OSError, ValueError, subprocess.SubprocessError):
            self.diagnostics.add("WORKTREE_CHANGED_OR_UNVERIFIABLE")
        payload = {
            "schema": f"smartci.runtime-observation.v{2 if self.detailed_contexts else 1}",
            "engine": self.engine,
            "complete": False,
            "omission_authorized": False,
            "commit": self.commit,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "implementation": platform.python_implementation(),
            "pytest": pytest.__version__,
            "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "tracked_blobs": dict(sorted(self.blobs.items())),
            "test_files": sorted(self.test_files),
            "case_count": self.case_count,
            "exit_code": int(exitstatus),
            "plugins": sorted(plugins),
            "diagnostics": sorted(self.diagnostics),
            "limitations": [
                "positive observations only; absence is not independence",
                "phase and fixture scopes are temporal attribution, not exclusive dependencies",
                "teardown and unknown scopes remain shared; cached fixture consumers are not inferred from first use",
                "native code and child processes incomplete; thread ownership not attributed",
                "async background work may cross test-call boundaries",
                "audit hooks are bypassable and imports may be cached",
                "open/import events are attempts; no contents or external paths recorded",
                "pre-plugin execution and restored transient mutations not covered",
            ],
            "contexts": {
                context: {
                    kind: sorted(values) for kind, values in sorted(kinds.items())
                }
                for context, kinds in sorted(self.contexts.items())
            },
        }
        if self.detailed_contexts:
            payload["context_metadata"] = dict(sorted(self.context_metadata.items()))
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["digest"] = hashlib.sha256(encoded.encode()).hexdigest()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting an input or prior run report.
        with self.output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")


STATE: pytest.StashKey[Observation] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--smartci-observation", help="Advisory runtime report outside repository"
    )
    parser.addoption(
        "--smartci-observation-engine",
        choices=["profile", "monitoring"],
        default="profile",
    )
    parser.addoption("--smartci-observation-contexts", action="store_true")


def pytest_configure(config: pytest.Config) -> None:
    destination = config.getoption("--smartci-observation")
    if not destination:
        return
    if hasattr(config, "workerinput") or getattr(config.option, "numprocesses", False):
        raise pytest.UsageError("runtime prototype supports serial pytest only")
    try:
        state = Observation(
            config.rootpath,
            Path(destination),
            engine=(
                "monitoring"
                if config.getoption("--smartci-observation-engine") == "monitoring"
                else "profile"
            ),
            detailed_contexts=config.getoption("--smartci-observation-contexts"),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise pytest.UsageError(
            "observation requires clean Git and a new external report"
        ) from exc
    config.stash[STATE] = state
    state.start()


def pytest_collection_finish(session: pytest.Session) -> None:
    if STATE in session.config.stash:
        state = session.config.stash[STATE]
        state.case_count = len(session.items)
        state.test_files = {state.test_context(item) for item in session.items} - {
            SHARED
        }


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_make_collect_report(collector: pytest.Collector) -> Generator[None]:
    state = collector.config.stash.get(STATE, None)
    if state is None or not state.detailed_contexts:
        yield
    else:
        scope = "module" if str(collector.path) in state.paths else "package"
        with state.phase("collection", scope, state.node_owner(collector, scope)):
            yield


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> Generator[None]:
    state = request.config.stash.get(STATE, None)
    if state is None or not state.detailed_contexts:
        yield
    else:
        with state.phase(
            "fixture_setup",
            request.scope,
            state.node_owner(request.node, request.scope),
        ):
            yield


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    state = item.config.stash.get(STATE, None)
    if state is not None:
        state.context = state.test_context(item)
    try:
        yield
    finally:
        if state is not None:
            state.context = SHARED


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if STATE in session.config.stash:
        plugins = [
            f"{dist.project_name.lower()}=={dist.version}"
            for _, dist in session.config.pluginmanager.list_plugin_distinfo()
        ]
        # Earlier session-finish hooks (for example snapshot plugins) can change
        # the result after the last test. The process wrapper remains authoritative.
        session.config.stash[STATE].finish(int(session.exitstatus), plugins)


def pytest_unconfigure(config: pytest.Config) -> None:
    if STATE in config.stash:
        config.stash[STATE].stop()
