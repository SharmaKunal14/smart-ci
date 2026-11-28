"""Small Maven Action boundary; released CLI owns planning and execution."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap

from smartci import action_control as control
from smartci import maven


def stage():
    if (
        os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or os.environ.get("RUNNER_OS") != "Linux"
    ):
        raise ValueError("experimental Maven Action requires hosted Linux")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    relative = os.environ["SOURCE_PATH"]
    repo = (
        workspace if relative == "." else workspace / control.relative(relative)
    ).resolve(strict=True)
    if not repo.is_relative_to(workspace):
        raise ValueError("checkout outside workspace")
    context = control.context(
        repo,
        Path(os.environ["GITHUB_EVENT_PATH"]),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_EVENT_NAME"],
    )
    config_path = control.relative(os.environ["CONFIG_PATH"])
    raw = control.base_file(context, config_path)
    maven.configuration(raw)
    state = bootstrap.state_root()
    state.mkdir(exist_ok=False)
    (state / "maven.toml").write_bytes(raw)
    control.write(state / "context.json", context)
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"state={state}\n")


def execute():
    state = bootstrap.state_root()
    context = control.read_object(state / "context.json")
    # Revalidate from the actual event; staged state is not a new trust authority.
    repo = Path(context["repo"])
    value = control.context(
        repo,
        Path(os.environ["GITHUB_EVENT_PATH"]),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_EVENT_NAME"],
    )
    config = maven.configuration(control.base_file(value, os.environ["CONFIG_PATH"]))
    if os.environ.get("CLI_READY") == "true":
        installation = control.read_object(state / "installation.json")
        args = [
            installation["python"],
            "-I",
            "-m",
            "smartci.cli",
            "maven",
            "--repo",
            str(repo),
            "--base",
            value["base"],
            "--head",
            value["head"],
            "--config",
            os.environ["CONFIG_PATH"],
            "--output",
            str(state / "result"),
        ]
        return subprocess.run(
            args,
            check=False,
            env={
                k: os.environ[k]
                for k in ("PATH", "HOME", "JAVA_HOME", "LANG", "TMPDIR")
                if k in os.environ
            },
            timeout=1080,
        ).returncode
    return maven.run(value, config, state / "result", force_full=True)


def summary():
    result = bootstrap.state_root() / "result"
    plan = control.read_object(result / "selection.json")
    execution = control.read_object(result / "execution.json")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
        stream.write(
            "### Experimental Maven selection\n\n```json\n"
            + json.dumps(
                {
                    "mode": plan["mode"],
                    "fallback": plan["fallback"],
                    "projects": plan.get("selected_projects", "full reactor"),
                    "execution": execution,
                },
                indent=2,
            )
            + "\n```\n"
        )


if __name__ == "__main__":
    try:
        operation = sys.argv[1]
        if operation == "stage":
            stage()
        elif operation == "execute":
            raise SystemExit(execute())
        elif operation == "summary":
            summary()
        else:
            raise ValueError("unknown operation")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("Maven Action failed; inspect retained native evidence.", flush=True)
        raise SystemExit(2)
