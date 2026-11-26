"""Observation adds evidence; it must never turn missing evidence into permission."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.adapters.runtime_observer import Observation
from smartci.discovery.models import Snapshot


def repository(tmp_path, files):
    root = tmp_path / "repo"
    root.mkdir()
    for path, content in {"pytest.ini": "[pytest]\n", **files}.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for args in [
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ]:
        subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, timeout=15
        )
    return root


def observe(root, output, *, extra=(), script=None):
    command = [sys.executable, "-m", "pytest"]
    if script:
        command = [sys.executable, "-c", script]
    environment = dict(os.environ)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [
            *command,
            "-p",
            "smartci.adapters.runtime_observer",
            "--smartci-observation",
            str(output),
            *extra,
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("engine", ["profile", "monitoring"])
def test_cached_import_calls_dynamic_targets_resources_and_shared_fixture(
    tmp_path, engine
):
    root = repository(
        tmp_path,
        {
            "library.py": "def value(): return 1\n",
            "dynamic.py": "def value(): return 2\n",
            "resource.txt": "fixture value\n",
            "test_a.py": "import library\ndef test_a(shared):\n    assert library.value() == 1\n",
            "test_b.py": "import library, importlib\ndef test_b(shared):\n    assert library.value() == 1\n    assert importlib.import_module('dynamic').value() == 2\n",
            "conftest.py": "import pytest\nfrom pathlib import Path\n@pytest.fixture(scope='session')\ndef shared():\n    return Path('resource.txt').read_text()\n",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-engine", engine))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert report["contexts"]["test_a.py"]["code_files"] == ["library.py", "test_a.py"]
    assert "library.py" in report["contexts"]["test_b.py"]["code_files"]
    assert "dynamic.py" in report["contexts"]["test_b.py"]["code_files"]
    assert "resource.txt" in report["contexts"]["@shared"]["open_attempts"]
    assert "resource.txt" not in report["contexts"]["test_b.py"].get(
        "open_attempts", []
    )
    assert report["case_count"] == 2
    assert report["test_files"] == ["test_a.py", "test_b.py"]
    assert report["complete"] is False and report["omission_authorized"] is False
    digest = report.pop("digest")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    with pytest.raises(ValidationError):
        Snapshot.model_validate(report)


def test_failure_keeps_exit_status_and_redacts_external_io_and_process_arguments(
    tmp_path,
):
    secret = tmp_path / "secret-do-not-record.txt"
    secret.write_text("unrelated private file contents")
    root = repository(
        tmp_path,
        {
            "test_a.py": f"import subprocess, sys\nfrom pathlib import Path\ndef test_a():\n    Path({str(secret)!r}).read_text()\n    subprocess.run([sys.executable, '-c', 'pass', 'private-argument'], check=True)\n    assert False\n",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output)
    assert result.returncode == 1
    text = output.read_text()
    report = json.loads(text)
    assert report["exit_code"] == 1
    assert "CHILD_PROCESS_NOT_OBSERVED" in report["diagnostics"]
    assert report["contexts"]["test_a.py"]["process_events"] == [
        "CHILD_PROCESS_ATTEMPT"
    ]
    assert "UNTRACKED_OR_EXTERNAL_OPENS_NOT_ATTRIBUTED" in report["diagnostics"]
    for value in [str(secret), secret.read_text(), "private-argument"]:
        assert value not in text


def test_changed_worktree_is_recorded_without_rewriting_native_result(tmp_path):
    root = repository(
        tmp_path,
        {
            "test_a.py": "from pathlib import Path\ndef test_a():\n    Path('data.txt').write_text('changed')\n",
            "data.txt": "original",
        },
    )
    output = tmp_path / "report.json"
    assert observe(root, output).returncode == 0
    assert (
        "WORKTREE_CHANGED_OR_UNVERIFIABLE"
        in json.loads(output.read_text())["diagnostics"]
    )


def test_session_finish_plugin_failure_is_preserved_in_observation(tmp_path):
    root = repository(
        tmp_path,
        {
            "test_a.py": "def test_a(): pass\n",
            "conftest.py": "import pytest\n@pytest.hookimpl(tryfirst=True)\ndef pytest_sessionfinish(session):\n    session.exitstatus = 3\n",
        },
    )
    output = tmp_path / "report.json"
    assert observe(root, output).returncode == 3
    assert json.loads(output.read_text())["exit_code"] == 3


@pytest.mark.parametrize("case", ["inside", "existing", "dirty", "parallel"])
def test_invalid_observation_setup_fails_explicitly(tmp_path, case):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    output = tmp_path / "report.json"
    extra = ()
    if case == "inside":
        output = root / "report.json"
    elif case == "existing":
        output.write_text("preserved")
    elif case == "dirty":
        (root / "test_a.py").write_text("def test_changed(): pass\n")
    else:
        # Mimic xdist's option without installing another plugin in the fixture.
        script = "import pytest, sys\nclass Parallel:\n def pytest_addoption(self, parser): parser.addoption('--numprocesses', type=int)\nsys.exit(pytest.main(sys.argv[1:], plugins=[Parallel()]))"
        result = observe(root, output, script=script, extra=("--numprocesses", "2"))
        assert result.returncode != 0
        assert "serial pytest only" in result.stderr
        return
    assert observe(root, output, extra=extra).returncode != 0
    if case == "existing":
        assert output.read_text() == "preserved"
    else:
        assert not output.exists()


def test_existing_profiler_is_preserved_and_missing_calls_disclosed(tmp_path):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    output = tmp_path / "report.json"
    script = "import pytest, sys\ndef profile(*args): pass\nsys.setprofile(profile)\ncode=pytest.main(sys.argv[1:])\nassert sys.getprofile() is profile\nsys.exit(code)"
    result = observe(root, output, script=script)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert "EXISTING_PROFILER_NOT_REPLACED" in report["diagnostics"]
    assert not report["complete"]


def test_observation_bounds_and_other_thread_attribution(tmp_path):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    observer = Observation(root, tmp_path / "report.json", limit=2)
    observer.active = True
    observer.add("code_files", "test_a.py")
    observer.add("code_files", "test_a.py")
    observer.main_thread = -1
    observer.add("code_files", "test_a.py")
    observer.add("code_entries", "test_a.py:1")
    assert observer.count == 2
    assert observer.contexts["@other-thread"]["code_files"] == {"test_a.py"}
    assert "OBSERVATION_LIMIT_REACHED" in observer.diagnostics
    observer.stop()
    observer.add("code_files", "never.py")
    assert observer.count == 2


def test_fixture_scope_collection_and_teardown_are_separate_without_fixture_changes(
    tmp_path,
):
    root = repository(
        tmp_path,
        {
            "dependency.py": "def value(): return 1\n",
            "setup.txt": "setup",
            "session.txt": "session",
            "teardown.txt": "teardown",
            "conftest.py": "import pytest\nfrom pathlib import Path\n@pytest.fixture(scope='session')\ndef shared():\n    yield Path('session.txt').read_text()\n    Path('teardown.txt').read_text()\n",
            "test_a.py": "import pytest, dependency\nfrom pathlib import Path\n@pytest.fixture\ndef local():\n    assert dependency.value() == 1\n    return Path('setup.txt').read_text()\ndef test_a(local, shared):\n    assert local == 'setup' and shared == 'session'\n",
            "test_b.py": "def test_b(shared): assert shared == 'session'\n",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-contexts",))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert report["schema"] == "smartci.runtime-observation.v2"

    def scopes(kind, value):
        return [
            report["context_metadata"].get(context, {"kind": context})
            for context, values in report["contexts"].items()
            if value in values.get(kind, [])
        ]

    assert scopes("open_attempts", "setup.txt") == [
        {"kind": "fixture_setup", "scope": "function", "owner": "test_a.py"}
    ]
    assert scopes("open_attempts", "session.txt") == [
        {"kind": "fixture_setup", "scope": "session", "owner": "."}
    ]
    assert scopes("open_attempts", "teardown.txt") == [{"kind": "@shared"}]
    assert {"kind": "collection", "scope": "module", "owner": "test_a.py"} in scopes(
        "code_files", "dependency.py"
    )
    assert report["complete"] is report["omission_authorized"] is False


@pytest.mark.parametrize("scope", ["module", "class", "package"])
def test_non_function_fixture_owners_use_their_native_scope(tmp_path, scope):
    root = repository(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/conftest.py": f"import pytest\nfrom pathlib import Path\n@pytest.fixture(scope={scope!r})\ndef data(): return Path('resource.txt').read_text()\n",
            "pkg/test_a.py": "class TestA:\n    def test_one(self, data): assert data == 'data'\n    def test_two(self, data): assert data == 'data'\n",
            "pkg/test_b.py": "class TestB:\n    def test_three(self, data): assert data == 'data'\n",
            "resource.txt": "data",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-contexts",))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    owners = {
        report["context_metadata"][key]["owner"]
        for key, values in report["contexts"].items()
        if "resource.txt" in values.get("open_attempts", [])
    }
    assert owners == (
        {"pkg"} if scope == "package" else {"pkg/test_a.py", "pkg/test_b.py"}
    )


def test_monitoring_keeps_existing_tool_and_profiler_and_releases_its_own_id(tmp_path):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    output = tmp_path / "report.json"
    script = """import pytest, sys
def profile(*args): pass
def callback(*args): pass
sys.setprofile(profile)
sys.monitoring.use_tool_id(1, 'existing-coverage')
sys.monitoring.register_callback(1, sys.monitoring.events.PY_START, callback)
sys.monitoring.set_events(1, sys.monitoring.events.PY_START)
code = pytest.main(sys.argv[1:])
assert sys.getprofile() is profile
assert sys.monitoring.get_tool(1) == 'existing-coverage'
assert sys.monitoring.get_events(1) == sys.monitoring.events.PY_START
assert sys.monitoring.get_tool(3) is None
assert sys.monitoring.get_tool(4) is None
sys.exit(code)
"""
    result = observe(
        root,
        output,
        script=script,
        extra=("--smartci-observation-engine", "monitoring"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text())["contexts"]["test_a.py"]["code_files"] == [
        "test_a.py"
    ]


def test_monitoring_slot_exhaustion_does_not_steal_another_tool(tmp_path):
    root = repository(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    output = tmp_path / "report.json"
    script = """import pytest, sys
for slot in (3, 4): sys.monitoring.use_tool_id(slot, 'already-in-use')
code = pytest.main(sys.argv[1:])
for slot in (3, 4): assert sys.monitoring.get_tool(slot) == 'already-in-use'
sys.exit(code)
"""
    result = observe(
        root,
        output,
        script=script,
        extra=("--smartci-observation-engine", "monitoring"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert "NO_MONITORING_TOOL_ID_AVAILABLE" in report["diagnostics"]
    assert report["complete"] is False


def test_monitoring_records_resumed_and_thrown_generators_without_exception_contents(
    tmp_path,
):
    root = repository(
        tmp_path,
        {
            "library.py": "def values():\n    yield 1\n    try: yield 2\n    except ValueError: yield 3\n",
            "conftest.py": "import pytest, library\n@pytest.fixture(scope='session')\ndef values(): return library.values()\n",
            "test_a.py": "def test_a(values): assert next(values) == 1\n",
            "test_b.py": "def test_b(values): assert next(values) == 2\n",
            "test_c.py": "def test_c(values): assert values.throw(ValueError('private-error-message')) == 3\n",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-engine", "monitoring"))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    for path in ("test_a.py", "test_b.py", "test_c.py"):
        assert "library.py" in report["contexts"][path]["code_files"]
    assert "private-error-message" not in output.read_text()


def test_failed_fixture_restores_context_before_other_tests(tmp_path):
    root = repository(
        tmp_path,
        {
            "library.py": "def value(): return 1\n",
            "test_a.py": "import pytest, library\n@pytest.fixture\ndef broken():\n    library.value()\n    raise ValueError('expected fixture error')\ndef test_a(broken): pass\n",
            "test_b.py": "import library\ndef test_b(): assert library.value() == 1\n",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-contexts",))
    assert result.returncode == 1
    report = json.loads(output.read_text())
    assert "library.py" in report["contexts"]["test_b.py"]["code_files"]
    assert report["exit_code"] == 1


def test_replaced_monitoring_slot_is_not_freed_by_observer(tmp_path):
    root = repository(
        tmp_path,
        {
            "test_a.py": "def test_a(): pass\n",
            "conftest.py": """import pytest, sys
@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    for slot in (3, 4):
        if (sys.monitoring.get_tool(slot) or '').startswith('smartci-observation-'):
            sys.monitoring.set_events(slot, 0)
            sys.monitoring.free_tool_id(slot)
            sys.monitoring.use_tool_id(slot, 'replacement')
def pytest_unconfigure(config):
    assert 'replacement' in [sys.monitoring.get_tool(slot) for slot in (3, 4)]
""",
        },
    )
    output = tmp_path / "report.json"
    result = observe(root, output, extra=("--smartci-observation-engine", "monitoring"))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert "MONITORING_TOOL_REPLACED_DURING_RUN" in report["diagnostics"]
