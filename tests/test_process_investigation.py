import hashlib
import json
import subprocess

import pytest

from smartci.contracts import Inventory
from smartci.contracts import TestUnit as Unit
from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.engine import investigate
from smartci.investigation.models import Inputs, Inspect, Limits, Propose
from smartci.investigation.process_scripts import PythonProcessScripts
from smartci.investigation.replay import DiagnosticReplay
from smartci.selection import Changes, Graph, SelectionPolicy

HEADER = "import subprocess\nimport sys\nfrom pathlib import Path\n"
BODY = """def test_child():
    child = (Path(__file__) / "../child.py").resolve().absolute()
    subprocess.run(f'echo q | "{sys.executable}" "{child}"', shell=True)
"""
SOURCE = HEADER + BODY


def inspect(source=SOURCE, catalog=None):
    return PythonProcessScripts().inspect(
        "tests/test_child.py",
        source.encode(),
        catalog if catalog is not None else {"tests/test_child.py", "tests/child.py"},
    )


def test_file_anchored_script_reference_in_pipeline_is_positive_only():
    facts = inspect()
    assert [fact.model_dump() for fact in facts] == [
        {"target": "tests/child.py", "line": 6}
    ]


@pytest.mark.parametrize(
    "expression",
    [
        'Path(__file__).with_name("child.py")',
        'Path(__file__).parent / "child.py"',
        '(Path(__file__) / "../child.py").resolve()',
    ],
)
def test_argv_and_import_aliases(expression):
    source = (
        "from subprocess import run as launch\n"
        "from sys import executable as python\n"
        "from pathlib import Path\n"
        f"child = {expression}\n"
        "launch([python, '-u', child], shell=False)\n"
    )
    assert [fact.target for fact in inspect(source)] == ["tests/child.py"]


@pytest.mark.parametrize(
    "before,after",
    [
        ('"../child.py"', '"../../secret.py"'),
        ('"../child.py"', '"/etc/passwd"'),
        ('"../child.py"', '"missing.py"'),
        ('"../child.py"', "input()"),
        ("def test_child():", "def test_child(subprocess):"),
        ("def test_child():", "def test_child(Path):"),
        ("def test_child():", "def test_child(__file__):"),
        ("def test_child():", "def test_child(sys):"),
        ("    subprocess.run(", '    child = "untrusted"\n    subprocess.run('),
        ("    subprocess.run(", "    subprocess.run = unknown\n    subprocess.run("),
        (
            "    subprocess.run(",
            "    if condition:\n        child = unknown\n    subprocess.run(",
        ),
        (
            "    subprocess.run(",
            "    if condition:\n        import other as subprocess\n    subprocess.run(",
        ),
        ("shell=True", "shell=setting"),
        ("shell=True", "shell=1"),
        ("shell=True", "**options"),
        ("{child}", "{child!r}"),
        ("{child}", "{child:format}"),
        ("echo q | ", "$(command) | "),
        ("echo q | ", "echo q && "),
        ("echo q | ", "echo q; "),
        ("echo q | ", "echo q || "),
        ("echo q | ", 'echo q "|" '),
        ('"{sys.executable}"', '"{sys.executable}" -c'),
        ('"{child}"', '"SMARTCI_ARGUMENT_0"'),
    ],
)
def test_unsupported_or_ambiguous_input_is_not_promoted(before, after):
    assert inspect(SOURCE.replace(before, after)) == []


def test_unknown_script_and_unanchored_cwd_relative_paths_not_inferred():
    assert inspect(catalog={"tests/test_child.py"}) == []
    assert inspect(HEADER + 'subprocess.run([sys.executable, "tests/child.py"])') == []
    assert inspect(HEADER + "from unknown import *\n" + BODY) == []


def test_source_is_parsed_without_executing_commands(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = HEADER + f"Path({str(marker)!r}).write_text('bad')\n" + BODY
    assert inspect(source)
    assert not marker.exists()


def test_syntax_bound_rejects_excessive_work(monkeypatch):
    monkeypatch.setattr("smartci.investigation.process_scripts.MAX_NODES", 10)
    with pytest.raises(ValueError, match="limit"):
        inspect()


@pytest.fixture
def repository(tmp_path):
    files = {
        "tests/test_child.py": SOURCE,
        "tests/child.py": "from app import App\n",
        "src/app.py": "class App: pass\n",
    }
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(source)

    def git(*args):
        return (
            subprocess.check_output(
                ["git", "-C", str(tmp_path), *args], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "Fixture",
    )
    revision = git("rev-parse", "HEAD")
    graph = Graph(
        schema_version="1",
        repository="example/repo",
        commit=revision,
        complete=False,
        owners={name: name for name in files},
        dependencies={name: [] for name in files},
        tests={"test": "tests/test_child.py"},
    )
    inputs = Inputs(
        changes=Changes(
            schema_version="1",
            repository=graph.repository,
            base=revision,
            head=revision,
            paths=["src/app.py"],
        ),
        inventory=Inventory(
            schema_version="1",
            repository=graph.repository,
            complete=True,
            environment="e" * 64,
            tests=[
                Unit(
                    id="test",
                    path="tests/test_child.py",
                    runner="pytest",
                    granularity="file",
                )
            ],
        ),
        base=graph,
        head=graph.model_copy(deep=True),
        policy=SelectionPolicy(
            schema_version="1", repository=graph.repository, mode="selective"
        ),
        sources={
            revision: {
                name: hashlib.sha256(source.encode()).hexdigest()
                for name, source in files.items()
            }
        },
        unresolved=["DYNAMIC_PROCESS:tests/test_child.py:6"],
    )
    return tmp_path, inputs


def test_diagnostic_tool_choice_adds_missing_edge_without_clearing_fallback(repository):
    root, inputs = repository
    before = inputs.model_dump_json()

    def run():
        limits = Limits()
        return investigate(
            inputs,
            Broker(
                root,
                inputs,
                PythonImports(["src"]),
                limits,
                additional_adapters=(PythonProcessScripts(),),
            ),
            DiagnosticReplay(),
            limits,
        )

    result = run()
    assert result == run()
    assert result["status"] == "finished" and result["model_calls"] == 0
    assert [x["kind"] for x in result["trace"]] == ["inspect", "propose", "finish"]
    edge = result["accepted_graph"]["evidence"][0]
    assert edge["target"] == "tests/child.py" and edge["already_recorded"] is False
    assert edge["verifier"] == "python-process-script-v1"
    assert result["final"]["execution"] == "full"
    assert result["final"]["fallback"] == ["INCOMPLETE_EVIDENCE"]
    assert result["unresolved"] == inputs.unresolved
    assert result["accepted_graph"]["base"]["complete"] is False
    assert inputs.model_dump_json() == before


def test_registration_and_relation_boundaries(repository):
    root, inputs = repository
    broker = Broker(root, inputs, PythonImports(["src"]), Limits())
    action = Inspect(
        kind="inspect",
        revision=inputs.head.commit,
        path="tests/test_child.py",
        adapter="python-process-script-v1",
    )
    with pytest.raises(ValueError, match="not registered"):
        broker.inspect(action)
    assert broker.bytes_read == 0
    broker = Broker(
        root,
        inputs,
        PythonImports(["src"]),
        Limits(),
        additional_adapters=(PythonProcessScripts(),),
    )
    observation = broker.inspect(action)
    proposal = Propose(
        kind="propose",
        revision=action.revision,
        path=action.path,
        target="tests/child.py",
        line=6,
        evidence=observation.evidence,
        relation="python_process_script_argument",
    )
    assert broker.verify(proposal).verifier == "python-process-script-v1"
    with pytest.raises(ValueError, match="matching evidence"):
        broker.verify(
            proposal.model_copy(update={"relation": "python_absolute_import"})
        )
    with pytest.raises(ValueError, match="duplicate"):
        Broker(
            root,
            inputs,
            PythonImports(["src"]),
            Limits(),
            additional_adapters=(PythonImports(["src"]),),
        )


def test_diagnostic_replay_does_not_invoke_unregistered_tool(repository):
    root, inputs = repository
    result = investigate(
        inputs,
        Broker(root, inputs, PythonImports(["src"]), Limits()),
        DiagnosticReplay(),
        Limits(),
    )
    assert result["source_bytes"] == 0
    assert result["accepted_graph"]["evidence"] == []
    assert result["final"]["execution"] == "full"


def test_cli_opt_in_is_offline_and_preserves_full_selection(
    repository, tmp_path, monkeypatch
):
    from smartci.cli import main

    root, inputs = repository
    input_path = tmp_path / "input.json"
    output = tmp_path / "result.json"
    input_path.write_text(inputs.model_dump_json())
    monkeypatch.setattr(
        "sys.argv",
        [
            "smartci",
            "investigate",
            "--inputs",
            str(input_path),
            "--repo",
            str(root),
            "--module-root",
            "src",
            "--provider",
            "diagnostic-replay",
            "--enable-process-inspection",
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    result = json.loads(output.read_bytes())
    assert len(result["accepted_graph"]["evidence"]) == 1
    assert result["model_calls"] == 0 and result["final"]["execution"] == "full"
