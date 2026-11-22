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


def test_cached_import_calls_dynamic_targets_resources_and_shared_fixture(tmp_path):
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
    result = observe(root, output)
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
