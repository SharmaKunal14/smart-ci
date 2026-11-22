"""Process execution cannot be represented as an import-only dependency map."""

import pytest
from test_discovery import analyse


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nsubprocess.run(['python', 'app.py'])",
        "import subprocess as sp\nsp.Popen(command)",
        "from subprocess import check_output as execute\nexecute(command)",
        "from subprocess import run\ncallback = run",
        "import subprocess\ncallback = subprocess.run",
        "import subprocess\ngetattr(subprocess, 'run')(command)",
        "import subprocess\ngetattr(subprocess, method)(command)",
        "import subprocess\nvars(subprocess)['run'](command)",
        "import subprocess\nsubprocess.__dict__['run'](command)",
        "from subprocess import *\nrun(command)",
        "import os\nos.system(command)",
        "from os import popen as launch\nlaunch(command)",
        "import os\nos.execv(program, arguments)",
        "import os\nos.posix_spawn(program, arguments, environment)",
        "import asyncio\nasync def launch():\n    await asyncio.create_subprocess_exec(program)",
        "from multiprocessing import Process\nProcess(target=run_app)",
        "import multiprocessing\nmultiprocessing.get_context('spawn').Pool()",
        "from concurrent.futures import ProcessPoolExecutor\nProcessPoolExecutor()",
        "import pty\npty.spawn(command)",
    ],
)
def test_process_launches_and_escaped_launchers_leave_explicit_gaps(source):
    result = analyse({"app.py": source})
    assert "DYNAMIC_PROCESS" in {gap.code for gap in result.gaps}


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nERROR = subprocess.CalledProcessError",
        "from subprocess import PIPE, CompletedProcess\nresult = CompletedProcess([], 0)",
        "import subprocess\ngetattr(subprocess, 'PIPE')",
        "import os\nvalue = os.getpid()",
    ],
)
def test_readonly_module_uses_do_not_imply_process_execution(source):
    assert not analyse({"app.py": source}).gaps


def test_call_and_escaped_reference_each_have_one_gap():
    result = analyse(
        {
            "app.py": "import subprocess\nsubprocess.run(command)\ncallback = subprocess.run\n"
        }
    )
    assert [(g.code, g.line) for g in result.gaps] == [
        ("DYNAMIC_PROCESS", 2),
        ("DYNAMIC_PROCESS", 3),
    ]
