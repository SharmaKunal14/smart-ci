"""Safety boundaries plus opt-in real TypeScript/Vitest contract tests."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.selection import fallback
from smartci.typescript.collector import collect, node_id
from smartci.typescript.collector import test_id as unit_id
from smartci.typescript.commands import execute, planning
from smartci.typescript.models import NativeReport, NativeResult, TypeScriptConfig
from smartci.typescript.native import NativeVitest, reconcile


@pytest.mark.parametrize("path", ["../tsconfig.json", "/tsconfig.json", "a//b", "a\\b"])
def test_reject_unsafe_project_paths(path):
    with pytest.raises(ValidationError):
        TypeScriptConfig(schema_version="1", repository="fixture", projects=[path])


def native_report(root, status="passed", names=("one",)):
    path = root / "tests" / "auth.test.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return NativeReport.model_validate(
        {
            "success": status != "failed",
            "testResults": [
                {
                    "name": str(path),
                    "assertionResults": [
                        {"title": name, "ancestorTitles": ["suite"], "status": status}
                        for name in names
                    ],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "status,code,names,expected",
    [
        ("passed", 0, ("one",), "passed"),
        ("failed", 1, ("one",), "failed"),
        ("pending", 0, ("one",), "incomplete"),
        ("passed", 1, ("one",), "incomplete"),
        ("passed", 0, (), "incomplete"),
        ("passed", 0, ("one", "extra"), "passed"),
        ("passed", 0, ("different",), "passed"),
        ("failed", 1, ("one", "extra"), "failed"),
    ],
)
def test_native_result_reconciliation(tmp_path, status, code, names, expected):
    # Reconciliation needs path validation only, not an installed runtime.
    runner = object.__new__(NativeVitest)
    runner.root = tmp_path
    result = reconcile(
        native_report(tmp_path, status, names),
        code,
        ["tests/auth.test.ts"],
        runner,
        0.0,
    )
    assert result.status == expected
    assert result.failed == (len(names) if status == "failed" else 0)


def test_native_report_cannot_escape_checkout(tmp_path):
    runner = object.__new__(NativeVitest)
    runner.root = tmp_path / "repo"
    with pytest.raises(ValueError):
        reconcile(native_report(tmp_path), 0, None, runner, 0.0)


@pytest.mark.parametrize(
    "expected",
    [[], ["tests/missing.test.ts"], ["tests/auth.test.ts", "tests/missing.test.ts"]],
)
def test_missing_or_extra_test_files_cannot_pass(tmp_path, expected):
    runner = object.__new__(NativeVitest)
    runner.root = tmp_path
    assert (
        reconcile(native_report(tmp_path), 0, expected, runner, 0.0).status
        == "incomplete"
    )


def test_invocation_removes_credentials_and_node_injection(tmp_path, monkeypatch):
    runner = object.__new__(NativeVitest)
    runner.root, runner.node, runner.prefix = tmp_path, "/usr/local/bin/node", []
    for name in ("AWS_ACCESS_KEY_ID", "OPENAI_API_KEY", "NODE_OPTIONS", "GH_TOKEN"):
        monkeypatch.setenv(name, "do-not-propagate")
    calls = []
    monkeypatch.setattr(
        "smartci.typescript.native.invoke", lambda *args: calls.append(args) or 0
    )
    assert runner.invoke(["example.js"]) == 0
    env = calls[0][3]
    assert not set(env) & {
        "AWS_ACCESS_KEY_ID",
        "OPENAI_API_KEY",
        "NODE_OPTIONS",
        "GH_TOKEN",
    }
    assert env["HOME"] != os.environ["HOME"]


def test_native_runner_preserves_default_isolation_and_bounds_workers(
    tmp_path, monkeypatch
):
    runner = object.__new__(NativeVitest)
    runner.root = tmp_path
    calls = []
    monkeypatch.setattr(
        runner, "invoke", lambda args, timeout: calls.append((args, timeout)) or 0
    )
    runner.vitest(["run"])
    args, timeout = calls[0]
    assert "--maxWorkers=2" in args and timeout == 600
    assert "--no-file-parallelism" not in args
    assert "--no-isolate" not in args and not any("pool" in arg for arg in args)
    assert "--allowOnly=false" in args and "--passWithNoTests=false" in args


def commit(root, message):
    for args in (
        ["add", "."],
        [
            "-c",
            "user.name=Smart CI Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            message,
        ],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.fixture
def native_project(tmp_path):
    dependencies = os.environ.get("SMARTCI_TYPESCRIPT_NODE_MODULES")
    if not dependencies or not shutil.which("node"):
        pytest.skip(
            "set SMARTCI_TYPESCRIPT_NODE_MODULES to installed TypeScript 5 / Vitest 3 dependencies"
        )
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        ".gitignore": "node_modules\n",
        "package.json": '{"type":"module","private":true}\n',
        "package-lock.json": "{}\n",
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "module": "NodeNext",
                    "moduleResolution": "NodeNext",
                    "strict": True,
                },
                "include": ["src/**/*.ts", "tests/**/*.ts"],
            }
        ),
        "vitest.config.ts": "import { defineConfig } from 'vitest/config';\nexport default defineConfig({test:{environment:'node',include:['tests/**/*.test.ts']}});\n",
        "src/auth.ts": "export const allowed = () => true;\n",
        "src/checkout.ts": "export { allowed } from './auth.js';\n",
        "src/other.ts": "export const other = () => 42;\n",
        "tests/auth.test.ts": "import {it,expect} from 'vitest'; import {allowed} from '../src/auth.js'; it('auth',()=>expect(allowed()).toBe(true));\n",
        "tests/checkout.test.ts": "import {it,expect} from 'vitest'; import {allowed} from '../src/checkout.js'; it('checkout',()=>expect(allowed()).toBe(true));\n",
        "tests/other.test.ts": "import {it,expect} from 'vitest'; import {other} from '../src/other.js'; it('other',()=>expect(other()).toBe(42));\n",
    }
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (root / "node_modules").symlink_to(
        Path(dependencies).resolve(), target_is_directory=True
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    base = commit(root, "baseline")
    config = TypeScriptConfig(
        schema_version="1", repository="fixture", projects=["tsconfig.json"]
    )
    return NativeVitest(root), config, base


def test_real_nodenext_graph_rebuild_and_defect(native_project, tmp_path):
    runner, config, base = native_project
    first = collect(runner, config)
    assert first.graph.complete and not first.gaps
    assert (
        node_id("src/auth.ts") in first.graph.dependencies[node_id("src/checkout.ts")]
    )
    assert len(first.files) == 3
    (runner.root / "src/auth.ts").write_text("export const allowed = () => false;\n")
    commit(runner.root, "auth defect")
    output = tmp_path / "proposal"
    output.mkdir()
    decision, snapshot = planning(runner, config, base, False, output)
    assert decision.execution == "subset" and decision.fallback == []
    assert decision.selected == sorted(
        unit_id(p) for p in ("tests/auth.test.ts", "tests/checkout.test.ts")
    )
    # Delete every map: deterministic planning rebuilds from source anyway.
    shutil.rmtree(output)
    output.mkdir()
    repeat, _ = planning(runner, config, base, False, output)
    assert repeat.model_dump() == decision.model_dump()
    attempts, mode, reasons = execute(runner, decision, snapshot)
    assert mode == "subset" and reasons == []
    assert attempts[0].status == "failed" and attempts[0].failed == 2
    full = runner.run(snapshot.files, subset=False)
    assert full.status == "failed" and full.failed == 2


def test_real_parallel_files_keep_isolated_globals(native_project):
    runner, _, _ = native_project
    for index in range(4):
        (runner.root / f"tests/isolation-{index}.test.ts").write_text(
            "import {it,expect} from 'vitest';\n"
            "const state = globalThis as typeof globalThis & {smartciLeak?: boolean};\n"
            "it('isolates files',()=>{expect(state.smartciLeak).toBeUndefined();state.smartciLeak=true;});\n"
        )
    commit(runner.root, "isolation probes")
    files = runner.collect()
    result = runner.run(files, subset=False)
    assert result.status == "passed" and result.cases == 7 and len(result.files) == 7


def test_removed_dependency_survives_in_union(native_project, tmp_path):
    runner, config, base = native_project
    (runner.root / "src/checkout.ts").write_text("export const allowed = () => true;\n")
    (runner.root / "src/auth.ts").write_text(
        "export const allowed = () => true; // changed\n"
    )
    commit(runner.root, "remove dependency")
    decision, _ = planning(runner, config, base, False, tmp_path)
    assert unit_id("tests/checkout.test.ts") in decision.selected
    assert unit_id("tests/other.test.ts") not in decision.selected


def test_added_dependency_and_rename_are_discovered(native_project, tmp_path):
    runner, config, base = native_project
    (runner.root / "src/auth.ts").rename(runner.root / "src/renamed.ts")
    for name in ("src/checkout.ts", "tests/auth.test.ts"):
        path = runner.root / name
        path.write_text(path.read_text().replace("auth.js", "renamed.js"))
    (runner.root / "src/other.ts").write_text(
        "import {allowed} from './renamed.js'; export const other = () => allowed() ? 42 : 0;\n"
    )
    commit(runner.root, "rename and introduce dependency")
    decision, snapshot = planning(runner, config, base, False, tmp_path)
    assert decision.fallback == []
    assert unit_id("tests/other.test.ts") in decision.selected
    assert (
        node_id("src/renamed.ts")
        in snapshot.graph.dependencies[node_id("src/other.ts")]
    )


def test_focused_tests_force_full_even_when_in_an_unrelated_file(
    native_project, tmp_path
):
    runner, config, base = native_project
    path = runner.root / "tests/other.test.ts"
    path.write_text(path.read_text().replace("it('other'", "it.only('other'"))
    commit(runner.root, "focused test")
    decision, snapshot = planning(runner, config, base, False, tmp_path)
    assert decision.execution == "full"
    assert "FOCUSED_TESTS_UNSUPPORTED" in snapshot.gaps


@pytest.mark.parametrize("kind", ["lock", "config", "missing_base", "outside_project"])
def test_real_fallbacks(native_project, tmp_path, kind):
    runner, config, base = native_project
    if kind == "lock":
        (runner.root / "package-lock.json").write_text('{"changed":true}\n')
    elif kind == "config":
        (runner.root / "vitest.config.ts").write_text(
            "export default {test:{environment:'node',include:['tests/**/*.test.ts']}};\n"
        )
    elif kind == "outside_project":
        (runner.root / "outside.ts").write_text("export const value = 1;\n")
    else:
        base = "0" * 40
        (runner.root / "src/auth.ts").write_text(
            "export const allowed = () => true; // changed\n"
        )
    commit(runner.root, kind)
    decision, snapshot = planning(runner, config, base, False, tmp_path)
    assert decision.execution == "full" and decision.fallback
    attempts, mode, _ = execute(runner, decision, snapshot)
    assert mode == "full" and attempts[-1].status == "passed"
    assert len(attempts[-1].files) == 3


@pytest.mark.parametrize(
    "code",
    [
        "import fs from 'node:fs'; export const other = () => 42;",
        "const name = './auth.js'; export const other = () => import(name);",
        "import {createRequire} from 'node:module'; export const other = () => 42;",
    ],
)
def test_opaque_modules_are_widened(native_project, code):
    runner, config, _ = native_project
    (runner.root / "src/other.ts").write_text(code)
    commit(runner.root, "opaque")
    snapshot = collect(runner, config)
    assert "src/other.ts" in snapshot.widened
    assert (
        node_id("src/auth.ts") in snapshot.graph.dependencies[node_id("src/other.ts")]
    )


def test_dirty_checkout_refuses_narrowing(native_project, tmp_path):
    runner, config, base = native_project
    (runner.root / "src/auth.ts").write_text(
        "export const allowed = () => true; // dirty\n"
    )
    decision, snapshot = planning(runner, config, base, False, tmp_path)
    assert decision.execution == "full" and snapshot is None


def test_subset_mismatch_retries_full(native_project, monkeypatch):
    runner, config, _ = native_project
    snapshot = collect(runner, config)
    report = fallback("test", snapshot.inventory)
    report.execution = "subset"
    report.fallback = []
    calls = []

    def run(expected, subset):
        calls.append(subset)
        return NativeResult(
            status="incomplete" if subset else "passed",
            files=[],
            cases=0,
            failed=1 if subset else 0,
            skipped=0,
            returncode=1 if subset else 0,
            duration_seconds=0.0,
        )

    monkeypatch.setattr(runner, "run", run)
    attempts, mode, reasons = execute(runner, report, snapshot)
    assert calls == [True, False] and mode == "full"
    assert reasons == ["INCOMPLETE_SUBSET_RESULTS"]
    assert attempts[0].failed == 1  # retained even though the retry passed
