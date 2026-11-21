"""Native project settings, reviewed skips and workspace safety boundaries."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.selection import digest
from smartci.typescript.collector import collect, node_id
from smartci.typescript.models import NativeProject, NativeReport, TypeScriptConfig
from smartci.typescript.native import NativeVitest, reconcile
from smartci.typescript.workspace import check_environment


def profile(**updates):
    return NativeProject.model_validate(
        {
            "kind": "vitest5-typescript7",
            "directory": "app",
            "configuration": "app/vitest.config.ts",
            "project": "main",
            "lockfile": "pnpm-lock.yaml",
            **updates,
        }
    )


@pytest.mark.parametrize(
    "update",
    [
        {"directory": "../outside"},
        {"configuration": "/tmp/config.ts"},
        {"project": "*"},
        {"project": "--run"},
        {"timezone": "unknown/zone"},
        {"kind": "anything"},
        {"lockfile": "../pnpm-lock.yaml"},
    ],
)
def test_profile_rejects_ambiguous_or_unsafe_scope(update):
    with pytest.raises(ValidationError):
        profile(**update)


def test_project_runner_preserves_native_parallelism_and_isolation(
    tmp_path, monkeypatch
):
    runner = object.__new__(NativeVitest)
    runner.root, runner.project = tmp_path, profile()
    calls = []
    monkeypatch.setattr(runner, "invoke", lambda args, timeout: calls.append(args) or 0)
    runner.vitest(["run"])
    args = calls[0]
    assert args[args.index("--project") + 1] == "main"
    assert not any(
        "Workers" in arg or "isolate" in arg or "pool" in arg or "parallel" in arg
        for arg in args
    )


def skip_report(tmp_path, status="skipped"):
    source = tmp_path / "app/test.ts"
    source.parent.mkdir(exist_ok=True)
    source.write_text("upstream test content\n")
    rule = {
        "path": "app/test.ts",
        "case": digest(["app/test.ts", ["suite"], "DST"]),
        "source_digest": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reason": "UTC has no DST transition",
    }
    runner = object.__new__(NativeVitest)
    runner.root, runner.project = tmp_path, profile(reviewed_skips=[rule])
    report = NativeReport.model_validate(
        {
            "success": status != "failed",
            "testResults": [
                {
                    "name": str(source),
                    "assertionResults": [
                        {"title": "DST", "ancestorTitles": ["suite"], "status": status}
                    ],
                }
            ],
        }
    )
    return runner, report, source


def test_exact_reviewed_skip_is_reported_not_erased(tmp_path):
    runner, report, _ = skip_report(tmp_path)
    result = reconcile(report, 0, ["app/test.ts"], runner, 1)
    assert result.status == "passed" and result.cases == result.skipped == 1
    assert result.reviewed_skips == [runner.project.reviewed_skips[0].case]


@pytest.mark.parametrize(
    "change", ["source", "title", "unexpected", "todo", "passed", "exit"]
)
def test_stale_or_unexpected_skip_cannot_pass(tmp_path, change):
    runner, report, source = skip_report(tmp_path)
    case = report.testResults[0].assertionResults[0]
    if change == "source":
        source.write_text("changed test")
    elif change == "title":
        case.title = "different"
    elif change == "unexpected":
        runner.project.reviewed_skips = []
    elif change in {"todo", "passed"}:
        case.status = change
    result = reconcile(report, 1 if change == "exit" else 0, ["app/test.ts"], runner, 1)
    assert result.status == "incomplete"


def test_stale_skip_review_preserves_observed_failure(tmp_path):
    runner, report, source = skip_report(tmp_path, "failed")
    source.write_text("changed")
    result = reconcile(report, 1, ["app/test.ts"], runner, 1)
    assert result.status == "incomplete" and result.failed == 1
    assert len(result.failed_cases) == 1


def commit(root):
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Smart CI Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.mark.parametrize("change", ["added", "deleted", "modified"])
def test_workspace_manifest_changes_prevent_environment_reuse(tmp_path, change):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9.0")
    nested = tmp_path / "pkg/package.json"
    nested.parent.mkdir()
    nested.write_text("{}")
    base = commit(tmp_path)
    if change == "added":
        (tmp_path / "pnpm-workspace.yaml").write_text("packages: [pkg]")
    elif change == "deleted":
        nested.unlink()
    else:
        nested.write_text('{"name":"changed"}')
    head = commit(tmp_path)
    with pytest.raises(ValueError, match="workspace"):
        check_environment(tmp_path, base, head, "pnpm-lock.yaml")


@pytest.fixture
def compiler_project(tmp_path):
    dependencies, node = (
        os.environ.get("SMARTCI_TS7_NODE_MODULES"),
        os.environ.get("SMARTCI_TS7_NODE"),
    )
    if not dependencies or not node:
        pytest.skip(
            "set SMARTCI_TS7_NODE_MODULES and SMARTCI_TS7_NODE for native compiler tests"
        )
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        ".gitignore": "node_modules\n",
        "package.json": '{"type":"module"}',
        "pnpm-lock.yaml": "lockfileVersion: 9.0",
        "app/tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "module": "NodeNext",
                    "moduleResolution": "NodeNext",
                },
                "include": ["**/*.ts", "../lib/**/*.ts"],
            }
        ),
        "app/vitest.config.ts": "import {defineConfig} from 'vitest/config'; export default defineConfig({test:{name:'main',include:['*.test.ts']}});",
        "app/auth.ts": "export {allowed} from '../lib/shared.js';",
        "lib/shared.ts": "export const allowed=true;",
        "app/auth.test.ts": "import {it,expect} from 'vitest'; import {allowed} from './auth.js'; it('auth',()=>expect(allowed).toBe(true));",
        "app/other.test.ts": "import {it,expect} from 'vitest'; it('other',()=>expect(42).toBe(42));",
    }
    for p, content in files.items():
        target = root / p
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(content)
    (root / "node_modules").symlink_to(
        Path(dependencies).resolve(), target_is_directory=True
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    commit(root)
    config = TypeScriptConfig(
        schema_version="1",
        repository="fixture",
        projects=["app/tsconfig.json"],
        native_project=profile(),
    )
    return NativeVitest(root, node=node, project=config.native_project), config


def test_native_compiler_resolves_transitive_dependencies_repeatably(compiler_project):
    runner, config = compiler_project
    snapshot = collect(runner, config)
    assert not snapshot.gaps
    assert (
        node_id("lib/shared.ts") in snapshot.graph.dependencies[node_id("app/auth.ts")]
    )
    assert (
        node_id("app/auth.ts")
        in snapshot.graph.dependencies[node_id("app/auth.test.ts")]
    )
    assert collect(runner, config).model_dump() == snapshot.model_dump()
    result = runner.run(snapshot.files, subset=False)
    assert result.status == "passed" and result.cases == 2


@pytest.mark.parametrize("kind", ["computed_import", "custom_plugin", "focused_test"])
def test_native_unknowns_widen_or_invalidate(compiler_project, kind):
    runner, config = compiler_project
    if kind == "computed_import":
        (runner.root / "app/auth.ts").write_text(
            "const filename='../lib/shared.js'; export const allowed=()=>import(filename);"
        )
    elif kind == "custom_plugin":
        p = runner.root / "app/vitest.config.ts"
        p.write_text(
            p.read_text().replace(
                "test:{", "plugins:[{name:'custom-transform'}],test:{"
            )
        )
    else:
        p = runner.root / "app/auth.test.ts"
        p.write_text(p.read_text().replace("it('auth'", "it.only('auth'"))
    commit(runner.root)
    snapshot = collect(runner, config)
    if kind == "computed_import":
        assert "app/auth.ts" in snapshot.widened
        assert (
            node_id("app/other.test.ts")
            in snapshot.graph.dependencies[node_id("app/auth.ts")]
        )
    else:
        assert not snapshot.graph.complete
        assert (
            "UNSUPPORTED_VITE_PLUGIN"
            if kind == "custom_plugin"
            else "FOCUSED_TESTS_UNSUPPORTED"
        ) in snapshot.gaps
