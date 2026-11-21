"""Compiler-backed file graph, with opaque consumers widened conservatively."""

import hashlib
import json
import platform
import tempfile
from pathlib import Path

import pydantic

from smartci.adapters.runners import read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.contracts import Inventory, TestUnit
from smartci.discovery.commands import write_json
from smartci.git_changes import git
from smartci.selection import Graph, digest

from .models import Analysis, TypeScriptConfig, TypeScriptSnapshot
from .native import NativeVitest
from .workspace import manifests


def node_id(path: str) -> str:
    return "file:" + digest(path)


def test_id(path: str) -> str:
    return "vitest:" + digest(path)


def tracked_files(root: Path, commit: str) -> list[str]:
    files = []
    for entry in git(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        if metadata.split()[0] not in {b"100644", b"100755"}:
            raise ValueError("symlinks and submodules are unsupported")
        path = raw_path.decode("utf-8")
        TestUnit.relative_path(path)
        if (root / path).is_symlink() or not (root / path).resolve().is_relative_to(
            root
        ):
            raise ValueError("path escaped repository")
        files.append(path)
    if len(files) > 100_000:
        raise ValueError("repository exceeds graph limit")
    return sorted(files)


def collect(runner: NativeVitest, config: TypeScriptConfig) -> TypeScriptSnapshot:
    root = runner.root
    commit = current_clean_head(root)
    if commit is None:
        raise ValueError("clean committed checkout required")
    files = tracked_files(root, commit)
    profile = config.native_project
    lockfile = profile.lockfile if profile else "package-lock.json"
    required = {
        "package.json",
        lockfile,
        profile.configuration if profile else "vitest.config.ts",
        *config.projects,
    }
    if not required <= set(files):
        raise ValueError("required configuration is untracked or missing")
    vitest = json.loads(read_bounded(root / "node_modules/vitest/package.json"))[
        "version"
    ]
    if not isinstance(vitest, str) or not vitest.startswith(
        "5.0." if profile else "3."
    ):
        raise ValueError("unsupported native Vitest version")
    tests: list[str] = []
    if not profile:
        print("smartci: collecting native Vitest inventory (1/2)", flush=True)
        tests = runner.collect()
        print("smartci: checking native collection repeatability (2/2)", flush=True)
        if runner.collect() != tests:
            raise ValueError("nondeterministic test collection")
    else:
        print(
            "smartci: collecting inventory and compiler map together (1/2)", flush=True
        )
    helper = Path(__file__).with_name(
        "inspect-native.mjs" if profile else "inspect.mjs"
    )
    with tempfile.TemporaryDirectory(prefix="smartci-analysis-") as temporary:
        request = Path(temporary) / "request.json"
        result = Path(temporary) / "result.json"
        write_json(
            request,
            {
                "files": files,
                "tests": sorted(tests),
                "projects": config.projects,
                "native_project": profile.model_dump() if profile else None,
            },
        )
        if runner.invoke([str(helper), str(root), str(request), str(result)]) != 0:
            raise ValueError("TypeScript analysis failed")
        analysis = Analysis.model_validate_json(read_bounded(result))
    if profile:
        # The helper resolves native configuration and discovers files once.
        # A separate CLI process must independently discover exactly that set.
        if not analysis.native_tests:
            raise ValueError("missing native inventory")
        tests = analysis.native_tests
        print("smartci: checking independent native collection (2/2)", flush=True)
        if runner.collect() != tests:
            raise ValueError("nondeterministic test collection")
    if not set(tests) <= set(files):
        raise ValueError("untracked native tests")
    if set(analysis.dependencies) != set(files):
        raise ValueError("graph is missing tracked files")
    node_ids = {p: node_id(p) for p in files}
    if any(d not in node_ids for deps in analysis.dependencies.values() for d in deps):
        raise ValueError("graph contains unknown dependencies")
    provenance = {
        "typescript": analysis.typescript,
        "vitest": vitest,
        "node": analysis.node,
        "platform": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "pydantic": pydantic.__version__,
        "configuration": digest(config.model_dump()),
        "lockfile": hashlib.sha256(read_bounded(root / lockfile)).hexdigest(),
        "implementation": digest(
            {
                p.relative_to(helper.parent.parent).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in sorted(helper.parent.parent.rglob("*"))
                if p.suffix in {".py", ".mjs"}
            }
        ),
    }
    if profile:
        provenance["manifests"] = digest(
            {
                p: hashlib.sha256(read_bounded(root / p)).hexdigest()
                for p in manifests(files, lockfile)
            }
        )
    inventory = Inventory(
        schema_version="1",
        repository=config.repository,
        complete=True,
        environment=digest(provenance),
        tests=[
            TestUnit(id=test_id(p), runner="vitest", granularity="file", path=p)
            for p in tests
        ],
    )
    graph = Graph(
        schema_version="1",
        repository=config.repository,
        commit=commit,
        complete=not analysis.gaps,
        owners=node_ids,
        dependencies={
            node_ids[p]: sorted(node_ids[d] for d in deps)
            for p, deps in sorted(analysis.dependencies.items())
        },
        tests={test_id(p): node_ids[p] for p in tests},
    )
    if current_clean_head(root) != commit:
        raise ValueError("workspace changed during collection")
    snapshot = TypeScriptSnapshot(
        schema_version="1",
        repository=config.repository,
        graph=graph,
        inventory=inventory,
        files=tests,
        widened=analysis.widened,
        gaps=analysis.gaps,
        analyzed=analysis.analyzed,
        provenance=provenance,
        warnings=analysis.warnings,
    )
    snapshot.digest = digest(snapshot.model_dump(exclude={"digest"}))
    return snapshot
