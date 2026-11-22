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
from pathlib import Path
from types import FrameType

import pytest

SHARED = "@shared"
OTHER_THREAD = "@other-thread"
LIMIT = 500_000


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
    def __init__(self, root: Path, output: Path, limit: int = LIMIT) -> None:
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
        filename = frame.f_code.co_filename
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
            self.add("code_entries", f"{path}:{frame.f_code.co_firstlineno}")

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

    def start(self) -> None:
        self.active = True
        sys.addaudithook(self.audit)
        sys.audit("smartci.observation.probe")
        if not self.audit_confirmed:
            self.diagnostics.add("AUDIT_HOOK_NOT_CONFIRMED")
        if sys.getprofile() is None:
            sys.setprofile(self.profile)
            self.profile_installed = True
        else:
            self.diagnostics.add("EXISTING_PROFILER_NOT_REPLACED")

    def stop(self) -> None:
        self.active = False
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
            "schema": "smartci.runtime-observation.v1",
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
                "collection/setup/teardown are shared across every test",
                "main-thread Python calls only; native code and child processes incomplete",
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


def pytest_configure(config: pytest.Config) -> None:
    destination = config.getoption("--smartci-observation")
    if not destination:
        return
    if hasattr(config, "workerinput") or getattr(config.option, "numprocesses", False):
        raise pytest.UsageError("runtime prototype supports serial pytest only")
    try:
        state = Observation(config.rootpath, Path(destination))
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
