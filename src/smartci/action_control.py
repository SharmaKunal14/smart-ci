"""Standard-library Action control plane; never import or execute PR configuration.

The Action bootstrap also uses this module when CLI installation fails. Only
the reviewed base revision can supply policy, adapter files and the full command.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from smartci.native_process import run_argv

MAX_FILE = 2 * 1024 * 1024
REPOSITORY = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
GIT = [
    "git",
    "--no-replace-objects",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
]


class Context(TypedDict):
    repository: str
    base: str
    head: str
    repo: str


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("JSON object required")
    return cast(dict[str, object], value)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_object(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("control input exceeds limit")
    return object_value(json.loads(raw, object_pairs_hook=unique_object))


def relative(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("relative path required")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(p in {"", ".", "..", ".git"} for p in value.split("/"))
        or any(c in value for c in "\\:\0\r\n")
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("normalized repository-relative path required")
    return value


def revision(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("exact Git revision required")
    return value


def git(repo: Path, *args: str, limit: int = MAX_FILE) -> bytes:
    with tempfile.TemporaryFile() as stream:
        subprocess.run(
            [*GIT, "-C", str(repo), *args],
            stdout=stream,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30,
        )
        stream.seek(0)
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Git control data exceeds limit")
    return raw


def context(repo: Path, event: Path, repository: str, event_name: str) -> Context:
    if event_name != "pull_request" or not re.fullmatch(REPOSITORY, repository):
        raise ValueError("ordinary pull_request event required")
    payload = read_object(event)
    pull = object_value(payload.get("pull_request"))
    base, head = object_value(pull.get("base")), object_value(pull.get("head"))
    if object_value(base.get("repo")).get("full_name") != repository:
        raise ValueError("PR base repository mismatch")
    if object_value(payload.get("repository")).get("full_name") != repository:
        raise ValueError("event repository mismatch")
    result: Context = {
        "repository": repository,
        "base": revision(base.get("sha")),
        "head": revision(head.get("sha")),
        "repo": str(repo),
    }
    verify_head(result)
    if git(repo, "cat-file", "-t", result["base"]).strip() != b"commit":
        raise ValueError("PR base commit unavailable; fetch full history")
    return result


def verify_head(value: Context) -> None:
    repo = Path(value["repo"]).resolve(strict=True)
    if (
        Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        != repo
    ):
        raise ValueError("repository root required")
    if git(repo, "rev-parse", "HEAD").decode().strip() != revision(value["head"]):
        raise ValueError("checkout must be the exact PR head")
    if git(repo, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("clean PR checkout required")


def base_file(value: Context, path: str) -> bytes:
    repo = Path(value["repo"])
    path = relative(path)
    rows = git(repo, "ls-tree", "-z", value["base"], "--", path).split(b"\0")
    if len(rows) != 2 or not rows[0] or rows[1]:
        raise ValueError("control file missing from PR base")
    metadata, actual = rows[0].split(b"\t", 1)
    mode, kind, sha = metadata.split()
    if mode not in {b"100644", b"100755"} or kind != b"blob" or actual.decode() != path:
        raise ValueError("regular base control file required")
    if int(git(repo, "cat-file", "-s", sha.decode())) > MAX_FILE:
        raise ValueError("control file exceeds size limit")
    return git(repo, "cat-file", "blob", sha.decode())


def prepare(
    value: Context, configuration: str, output: Path, action_root: Path | None = None
) -> dict[str, object]:
    repo = Path(value["repo"])
    if output.is_relative_to(repo) or repo.is_relative_to(output):
        raise ValueError("external Action output required")
    raw = base_file(value, configuration)
    policy = object_value(json.loads(raw, object_pairs_hook=unique_object))
    if "profile" in policy:
        # Presets are code from the pinned Action, never supplied by the PR.
        if (
            action_root is None
            or policy.get("schema_version") != "1"
            or policy.get("profile") != "abseil-gcc-cpp17-v1"
            or policy.keys()
            - {
                "schema_version",
                "profile",
                "publisher",
                "publisher_capture",
                "must_run",
            }
        ):
            raise ValueError("unsupported native profile configuration")
        preset = read_object(action_root / "action/profiles/abseil-gcc-cpp17-v1.json")
        for section in ("capture", "execution"):
            profile = object_value(object_value(preset[section])["profile"])
            profile["repository"] = value["repository"]
        for key in ("publisher", "publisher_capture", "must_run"):
            if key in policy:
                preset[key] = policy[key]
        policy = preset
    required = {"schema_version", "files", "capture", "execution", "fallback"}
    if not required <= policy.keys() or policy.keys() - required - {
        "publisher",
        "publisher_capture",
        "must_run",
    }:
        raise ValueError("unsupported Action configuration fields")
    if policy["schema_version"] != "1":
        raise ValueError("unsupported Action configuration version")
    files = policy["files"]
    if (
        not isinstance(files, list)
        or len(files) > 64
        or len(set(map(str, files))) != len(files)
    ):
        raise ValueError("bounded unique control file list required")
    output.mkdir(mode=0o700, exist_ok=False)
    control = output / "control"
    control.mkdir()
    total = 0
    for item in files:
        name = relative(item)
        data = base_file(value, name)
        total += len(data)
        if total > 8 * 1024 * 1024:
            raise ValueError("control files exceed aggregate limit")
        destination = control / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
    # Only argv values in locally executed commands receive this trusted-path
    # substitution. Publisher command identity must remain exactly as published.
    for section, commands in (
        ("capture", ("native", "query")),
        ("execution", ("full", "subset")),
    ):
        block = object_value(policy[section])
        for key in commands:
            expand_command(object_value(block[key]), control, action_root)
    expand_command(object_value(policy["fallback"]), control, action_root)
    write(output / "context.json", dict(value))
    write(output / "policy.json", policy)
    return policy


def expand_command(
    command: dict[str, object], control: Path, action_root: Path | None = None
) -> None:
    if set(command) != {"argv", "timeout_seconds"}:
        raise ValueError("unsupported command fields")
    arguments = command["argv"]
    timeout = command["timeout_seconds"]
    if (
        not isinstance(arguments, list)
        or not 1 <= len(arguments) <= 64
        or any(
            not isinstance(a, str)
            or not a
            or len(a) > 4096
            or any(c in a for c in "\0\r\n")
            for a in arguments
        )
        or type(timeout) is not int
        or not 1 <= timeout <= 1800
    ):
        raise ValueError("invalid bounded command")
    values = [cast(str, a).replace("{control}", str(control)) for a in arguments]
    if action_root is not None:
        values = [a.replace("{action}", str(action_root)) for a in values]
    if (
        not Path(values[0]).is_absolute()
        or "{repo}" in values[0]
        or "{capture}" in values[0]
    ):
        raise ValueError("trusted absolute executable required")
    command["argv"] = values


def write(path: Path, value: dict[str, object]) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def full_fallback(value: Context, policy: dict[str, object], output: Path) -> int:
    verify_head(value)
    command = object_value(policy["fallback"])
    capture = output / "installation-fallback"
    capture.mkdir(mode=0o700)
    arguments = [
        str(a).replace("{repo}", value["repo"]).replace("{capture}", str(capture))
        for a in cast(list[str], command["argv"])
    ]
    timeout = command["timeout_seconds"]
    if type(timeout) is not int:
        raise ValueError("integer timeout required")
    print("CLI unavailable; running the reviewed independent full command.", flush=True)
    code = run_argv(arguments, Path(value["repo"]), timeout)
    verify_head(value)
    write(
        output / "fallback.json",
        {
            "mode": "full",
            "reason": "CLI_UNAVAILABLE",
            "exit_code": code,
            "model_calls": 0,
        },
    )
    return code if 0 <= code <= 255 else 1
