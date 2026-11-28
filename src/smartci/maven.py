"""Experimental Maven reactor selection under a reviewed declared-input contract.

This is module selection, not Java call-graph analysis. A Maven model cannot
prove the absence of arbitrary filesystem/network dependencies. Until that
contract is reviewed, the independent native command remains mandatory.
"""

import argparse
import hashlib
import os
import re
import signal
import subprocess
import time
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import action_control as control

NS = {"m": "http://maven.apache.org/POM/4.0.0"}
MAX_MODEL = 8 * 1024 * 1024
HELP = "org.apache.maven.plugins:maven-help-plugin:3.5.1:effective-pom"


@dataclass(frozen=True)
class Config:
    command: tuple[str, ...]
    timeout: int
    contract: str
    reviewed_tree: str


@dataclass(frozen=True)
class Project:
    path: str
    coordinate: str
    dependencies: frozenset[str]
    packaging: str = "jar"


def configuration(raw: bytes) -> Config:
    data = tomllib.loads(raw.decode())
    if set(data) != {
        "schema_version",
        "command",
        "timeout_seconds",
        "input_contract",
        "reviewed_native_tree_sha256",
    }:
        raise ValueError("invalid Maven configuration fields")
    argv = data["command"]
    timeout = data["timeout_seconds"]
    if (
        data["schema_version"] != "1"
        or not isinstance(argv, list)
        or not 1 <= len(argv) <= 40
        or any(
            not isinstance(a, str)
            or not a
            or len(a) > 1024
            or any(c in a for c in "\0\r\n")
            for a in argv
        )
        or argv[0] != "./mvnw"
        or type(timeout) is not int
        or not 1 <= timeout <= 900
        or not isinstance(data["input_contract"], str)
        or data["input_contract"] not in {"unreviewed", "declared-reactor-inputs-v1"}
        or not isinstance(data["reviewed_native_tree_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", data["reviewed_native_tree_sha256"])
    ):
        raise ValueError("invalid Maven configuration")
    # The base-owned full command is preserved verbatim. Selection must not
    # start with an already-filtered reactor or a resume/nonrecursive command.
    forbidden = ("--projects", "--resume", "--also-make", "--non-recursive")
    if any(a.startswith((*forbidden, "-pl", "-rf", "-am")) or a == "-N" for a in argv):
        raise ValueError("independent full-reactor command required")
    return Config(
        tuple(argv),
        timeout,
        data["input_contract"],
        data["reviewed_native_tree_sha256"],
    )


def text(element: ET.Element, path: str, default: str = "") -> str:
    return element.findtext(path, default=default, namespaces=NS).strip()


def coordinate(element: ET.Element, plugin: bool = False) -> str:
    group = text(element, "m:groupId", "org.apache.maven.plugins" if plugin else "")
    artifact = text(element, "m:artifactId")
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", s) for s in (group, artifact)):
        raise ValueError("unresolved Maven coordinate")
    return group + ":" + artifact


def models(raw: bytes, repo: Path) -> dict[str, Project]:
    if (
        len(raw) > MAX_MODEL
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        raise ValueError("invalid model XML")
    root = ET.fromstring(raw)
    if root.tag != "projects" or not 1 <= len(root) <= 500:
        raise ValueError("complete bounded reactor models required")
    result: dict[str, Project] = {}
    coordinates: set[str] = set()
    declared: set[str] = {"."}
    for node in root:
        if node.tag != "{" + NS["m"] + "}project":
            raise ValueError("unexpected model namespace")
        directory = Path(text(node, "m:build/m:directory"))
        if not directory.is_absolute() or directory.name != "target":
            raise ValueError("nonstandard build directory")
        directory = directory.parent
        if not directory.is_relative_to(repo) or directory != directory.resolve():
            raise ValueError("model directory outside checkout")
        path = directory.relative_to(repo).as_posix()
        if path != ".":
            control.relative(path)
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or path.startswith("-"):
            raise ValueError("unsupported module path")
        identity = coordinate(node)
        if path in result or identity in coordinates:
            raise ValueError("ambiguous reactor project")
        if text(node, "m:packaging", "jar") not in {"pom", "jar"}:
            raise ValueError("unsupported packaging")
        for field, suffix in (
            ("sourceDirectory", "src/main/java"),
            ("testSourceDirectory", "src/test/java"),
        ):
            if text(node, "m:build/m:" + field) != str(directory / suffix):
                raise ValueError("nonstandard source roots")
        for element in node.findall(
            "m:build/m:resources/m:resource/m:directory", NS
        ) + node.findall("m:build/m:testResources/m:testResource/m:directory", NS):
            value = Path(element.text or "")
            if value not in {
                directory / "src/main/resources",
                directory / "src/test/resources",
            }:
                raise ValueError("nonlocal resources")
        if node.findall("m:build/m:extensions/m:extension", NS):
            raise ValueError("unsupported build extension")
        for module in node.findall("m:modules/m:module", NS):
            child = control.relative(module.text or "")
            declared.add((directory / child).relative_to(repo).as_posix())
        deps = {coordinate(d) for d in node.findall("m:dependencies/m:dependency", NS)}
        parent = node.find("m:parent", NS)
        if parent is not None:
            deps.add(coordinate(parent))
        for plugin in node.findall("m:build/m:plugins/m:plugin", NS):
            deps.add(coordinate(plugin, plugin=True))
            deps.update(
                coordinate(d) for d in plugin.findall("m:dependencies/m:dependency", NS)
            )
        result[path] = Project(
            path, identity, frozenset(deps), text(node, "m:packaging", "jar")
        )
        coordinates.add(identity)
    if set(result) != declared:
        raise ValueError("incomplete reactor")
    return result


def select(projects: dict[str, Project], paths: list[str]) -> dict[str, object]:
    all_paths = sorted(projects)
    owners: set[str] = set()
    for path in paths:
        control.relative(path)
        matches = [
            p
            for p in projects
            if p != "."
            and any(
                path.startswith(p + "/src/" + kind + "/java/")
                and path.endswith(".java")
                for kind in ("main", "test")
            )
        ]
        if len(matches) != 1:
            return {
                "mode": "full",
                "selected_projects": all_paths,
                "fallback": ["GLOBAL_OR_UNSUPPORTED_CHANGE"],
            }
        owners.add(matches[0])
    if not owners:
        return {
            "mode": "full",
            "selected_projects": all_paths,
            "fallback": ["NO_ELIGIBLE_CHANGE"],
        }
    by_coordinate = {p.coordinate: key for key, p in projects.items()}
    dependencies = {
        key: {by_coordinate[d] for d in p.dependencies if d in by_coordinate}
        for key, p in projects.items()
    }
    # First downstream impact, then build prerequisites. Do not expand downstream
    # from an unchanged prerequisite: that would select unrelated siblings.
    impacted = set(owners)
    while True:
        expanded = impacted | {p for p, deps in dependencies.items() if deps & impacted}
        if expanded == impacted:
            break
        impacted = expanded
    # Retain all aggregator checks, not only the root. They may inspect the
    # entire source tree even when no Java test belongs to their project.
    selected = (
        impacted
        | {"."}
        | {p for p, model in projects.items() if model.packaging == "pom"}
    )
    while True:
        expanded = selected | set().union(*(dependencies[p] for p in selected))
        if expanded == selected:
            break
        selected = expanded
    return {
        "mode": "full" if selected == set(projects) else "subset",
        "changed_projects": sorted(owners),
        "impacted_projects": sorted(impacted),
        "selected_projects": sorted(selected),
        "omitted_projects": sorted(set(projects) - selected),
        "fallback": [],
    }


def changes(value: control.Context) -> list[str]:
    repo = Path(value["repo"])
    control.verify_head(value)
    if control.git(repo, "ls-files", "--others", "-z"):
        raise ValueError("ignored or untracked inputs")
    if (
        control.git(repo, "merge-base", "--all", value["base"], value["head"])
        .decode()
        .strip()
        != value["base"]
    ):
        raise ValueError("base must be exact ancestor")
    for sha in (value["base"], value["head"]):
        tree = control.git(repo, "ls-tree", "-rz", sha, limit=16 * 1024 * 1024)
        if any(row.startswith((b"120000 ", b"160000 ")) for row in tree.split(b"\0")):
            raise ValueError("symlinks or submodules")
    # --no-renames lists old and new paths independently, retaining both owners.
    raw = control.git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        value["base"],
        value["head"],
        "--",
    )
    return sorted({p for p in raw.decode().split("\0") if p})


def native_tree(repo: Path, revision: str) -> str:
    """Bind the reviewed contract to native inputs, not a reusable boolean.

    This contract excludes .github orchestration from native runtime inputs;
    changes there still cause full execution on their own PR. A native base
    update invalidates this first experimental profile until re-reviewed.
    """
    rows = control.git(
        repo, "ls-tree", "-rz", control.revision(revision), limit=16 * 1024 * 1024
    ).split(b"\0")
    native = [r for r in rows if r and not r.split(b"\t", 1)[1].startswith(b".github/")]
    return hashlib.sha256(b"\0".join(native)).hexdigest()


def invoke(argv: list[str], repo: Path, log: Path, timeout: int) -> int:
    allowed = (
        "HOME",
        "PATH",
        "JAVA_HOME",
        "LANG",
        "LC_ALL",
        "USER",
        "LOGNAME",
        "TMPDIR",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(CI="true", GITHUB_ACTIONS="true")
    # Environment filtering is not filesystem isolation. Native code must run on
    # a disposable runner without persisted credentials or privileged services.
    with (
        log.open("xb") as stream,
        subprocess.Popen(
            argv,
            cwd=repo,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process,
    ):
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 124
                try:
                    return process.wait(timeout=min(15, remaining))
                except subprocess.TimeoutExpired:
                    print("Native Maven command is still running...", flush=True)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def run(
    value: control.Context, config: Config, output: Path, force_full: bool = False
) -> int:
    repo = Path(value["repo"]).resolve(strict=True)
    if output.resolve().is_relative_to(repo):
        raise ValueError("output must be outside checkout")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    plan: dict[str, object] = {"mode": "full", "fallback": ["FORCED_FULL"]}
    if not force_full:
        try:
            if config.contract != "declared-reactor-inputs-v1":
                raise ValueError("unreviewed input contract")
            if native_tree(repo, value["base"]) != config.reviewed_tree:
                raise ValueError("reviewed native inputs changed")
            paths = changes(value)
            # Configuration/global changes bypass metadata entirely. The narrow
            # profile does not reuse an obsolete base graph after POM changes.
            if not paths or any(not p.endswith(".java") for p in paths):
                plan = {"mode": "full", "fallback": ["GLOBAL_OR_UNSUPPORTED_CHANGE"]}
            else:
                code = invoke(
                    [
                        *config.command,
                        HELP,
                        "-Doutput=" + str(output / "effective-pom.xml"),
                    ],
                    repo,
                    output / "model.log",
                    120,
                )
                if code:
                    raise ValueError("native model collection failed")
                control.verify_head(value)
                with (output / "effective-pom.xml").open("rb") as stream:
                    raw = stream.read(MAX_MODEL + 1)
                projects = models(raw, repo)
                plan = select(projects, paths)
                plan["model_sha256"] = hashlib.sha256(raw).hexdigest()
                plan["changed_paths"] = paths
        except (ValueError, OSError, subprocess.SubprocessError, ET.ParseError):
            plan = {"mode": "full", "fallback": ["INCOMPLETE_EVIDENCE"]}
    argv = list(config.command)
    if plan["mode"] == "subset":
        selected = plan["selected_projects"]
        assert isinstance(selected, list) and all(isinstance(p, str) for p in selected)
        argv += ["--projects", ",".join(selected)]
    plan.update(
        schema_version="1",
        base=value["base"],
        head=value["head"],
        command=argv,
        input_contract=config.contract,
    )
    control.write(output / "selection.json", plan)
    planning_seconds = time.monotonic() - started
    print(f"Maven plan: {plan['mode']}; fallback={plan['fallback']}", flush=True)
    execution_started = time.monotonic()
    code = invoke(argv, repo, output / "native.log", config.timeout)
    control.write(
        output / "execution.json",
        {
            "exit_code": code,
            "planning_seconds": planning_seconds,
            "native_seconds": time.monotonic() - execution_started,
            "total_seconds": time.monotonic() - started,
        },
    )
    return code


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "maven", help="experimental reviewed Maven reactor execution"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--config", default=".github/smartci-maven.toml")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force-full", action="store_true")


def command(args: argparse.Namespace) -> int:
    try:
        value: control.Context = {
            "repo": str(args.repo.resolve(strict=True)),
            "base": control.revision(args.base),
            "head": control.revision(args.head),
            "repository": "local/repository",
        }
        control.verify_head(value)
        config = configuration(control.base_file(value, args.config))
        return run(value, config, args.output.resolve(), args.force_full)
    except (ValueError, OSError, subprocess.SubprocessError):
        print(
            "Maven control or native execution failed; no successful result is claimed.",
            flush=True,
        )
        return 2
