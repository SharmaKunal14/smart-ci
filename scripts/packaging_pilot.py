"""Pinned existing-repository acceptance harness. All mutations stay in its disposable clone."""

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.adapters.suite import current_clean_head
from smartci.discovery.collector import collect
from smartci.discovery.commands import plan_command, write_json
from smartci.discovery.models import PythonConfig
from smartci.discovery.planning import plan
from smartci.reports import atomic_write, markdown
from smartci.selection import SelectionPolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "demo-output/onboarding/packaging"
EXAMPLE = ROOT / "examples/onboarding/packaging"
URL = "https://github.com/pypa/packaging.git"
REVISION = "929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5"


def run(command, cwd, *, capture=False, env=None, timeout=300):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"{command[0]} failed with exit {result.returncode}; workspace retained for inspection"
        )
    return result.stdout.strip() if capture else None


def setup(workspace):
    if workspace.exists():
        raise RuntimeError(
            "setup requires a new workspace; use --workspace to choose another directory"
        )
    workspace.mkdir(parents=True)
    repo = workspace / "repository"
    python = workspace / "environment/bin/python"
    print(
        "Downloading the pinned public repository and installing its isolated test environment...",
        flush=True,
    )
    run(["git", "clone", URL, str(repo)], ROOT)
    run(["git", "checkout", "--detach", REVISION], repo)
    run(["uv", "venv", "--python", sys.executable, str(python.parents[1])], ROOT)
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(EXAMPLE / "requirements.txt"),
        ],
        ROOT,
    )
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-build-isolation",
            "--no-deps",
            "-e",
            str(repo),
        ],
        ROOT,
    )
    run(["uv", "build", "--wheel", "--out-dir", str(workspace / "wheel")], ROOT)
    wheels = list((workspace / "wheel").glob("smartci-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("expected one Smart CI wheel")
    run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])],
        ROOT,
    )
    write_json(workspace / "setup.json", {"repository": URL, "revision": REVISION})
    print(
        f"Ready: {workspace}. No CI workflow or hosted service has been changed.",
        flush=True,
    )


def native_results(path, repo):
    raw = read_bounded(path, 32 * 1024 * 1024)
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw or b"\x00" in raw:
        raise RuntimeError("unsupported native XML")
    observed = {}
    for case in ET.fromstring(raw).iter("testcase"):
        names = case.attrib["classname"].split(".")
        candidates = [
            i
            for i in range(1, len(names) + 1)
            if (repo / ("/".join(names[:i]) + ".py")).is_file()
        ]
        if len(candidates) != 1:
            raise RuntimeError("ambiguous native case identity")
        split = candidates[0]
        target = "::".join(
            ["/".join(names[:split]) + ".py", *names[split:], case.attrib["name"]]
        )
        if target in observed:
            raise RuntimeError("duplicate native case identity")
        observed[target] = (
            "failed"
            if case.find("failure") is not None or case.find("error") is not None
            else "skipped"
            if case.find("skipped") is not None
            else "passed"
        )
    if not observed:
        raise RuntimeError("empty native baseline")
    return observed


def verify(workspace):
    if json.loads((workspace / "setup.json").read_text()) != {
        "repository": URL,
        "revision": REVISION,
    }:
        raise RuntimeError("unrecognized managed workspace")
    repo = workspace / "repository"
    python = str(workspace / "environment/bin/python")
    if (
        current_clean_head(repo) != REVISION
        or run(["git", "remote", "get-url", "origin"], repo, capture=True) != URL
    ):
        raise RuntimeError(
            "pilot requires its clean pinned checkout; no files were reset"
        )
    if any(
        os.environ.get(k)
        for k in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        )
    ):
        raise RuntimeError(
            "pilot requires an environment without ambient pytest/import overrides"
        )
    for number in range(1, 1001):
        output = workspace / (
            "verification" if number == 1 else f"verification-{number}"
        )
        try:
            output.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError(
            "verification artifact limit reached; choose a new workspace"
        )
    config = PythonConfig.model_validate_json((EXAMPLE / "config.json").read_bytes())
    policy = SelectionPolicy.model_validate_json((EXAMPLE / "policy.json").read_bytes())
    records = []
    baseline_xml = output / "native-baseline.xml"
    started = time.monotonic()
    print("native baseline: starting full pytest execution (up to 300s)...", flush=True)
    run([python, "-m", "pytest", "-q", f"--junitxml={baseline_xml}"], repo)
    native_duration = time.monotonic() - started
    native = native_results(baseline_xml, repo)
    skipped = {case for case, outcome in native.items() if outcome == "skipped"}
    print(
        f"Native baseline: {len(native)} cases, {len(skipped)} skipped; {native_duration:.2f}s",
        flush=True,
    )

    def capture(
        name, base=None, expected=None, failed_files=frozenset(), full_reason=None
    ):
        directory = output / name
        directory.mkdir()
        started = time.monotonic()
        print(
            f"{name}: collecting revision-bound evidence (two native discoveries)...",
            flush=True,
        )
        snapshot, runner, units = collect(repo, config, python)
        collection_duration = time.monotonic() - started
        write_json(directory / "snapshot.json", snapshot.model_dump())
        write_json(directory / "inventory.json", snapshot.inventory.model_dump())
        write_json(directory / "head-graph.json", snapshot.graph.model_dump())
        write_json(directory / "provenance.json", snapshot.provenance.model_dump())
        proposal = None
        if base is not None:
            write_json(directory / "base-graph.json", base.graph.model_dump())
            proposal = plan(repo, base, snapshot, policy)
            write_json(directory / "selection.json", proposal.model_dump())
            atomic_write(directory / "audit.md", markdown(proposal))
            if proposal != plan(repo, base, snapshot, policy):
                raise RuntimeError("non-repeatable selection")
            selected = {
                t.path for t in snapshot.inventory.tests if t.id in proposal.selected
            }
            if proposal.execution != "full" or (
                expected is not None and selected != expected
            ):
                raise RuntimeError(f"unexpected candidate plan in {name}")
            if full_reason is not None and full_reason not in proposal.fallback:
                raise RuntimeError(f"expected fallback missing in {name}")
            if full_reason is None and proposal.fallback:
                raise RuntimeError(
                    f"unexpected fallback in {name}: {proposal.fallback}"
                )
        # Persist the proposal BEFORE obtaining ground truth. Every scenario runs full.
        saved = "plan saved" if proposal is not None else "baseline evidence saved"
        print(
            f"{name}: {saved}; starting FULL suite ({len(runner.pytest_cases)} cases, timeout 120s)...",
            flush=True,
        )
        result = runner.run(units)
        write_json(directory / "full-result.json", asdict(result))
        write_json(directory / "native-results.json", runner.native_results)
        actual_failed = {
            case.split("::")[0]
            for case, outcome in runner.native_results.items()
            if outcome == "failed"
        }
        actual_skipped = {
            case
            for case, outcome in runner.native_results.items()
            if outcome == "skipped"
        }
        if actual_failed != set(failed_files) or actual_skipped != skipped:
            raise RuntimeError(f"unexpected failures/skips in {name}")
        if set(runner.native_results) != set(runner.pytest_cases) or set(
            result.observed
        ) != {u.id for u in units}:
            raise RuntimeError(f"incomplete native reconciliation in {name}")
        if (
            result.returncode != (1 if failed_files else 0)
            or current_clean_head(repo) != snapshot.graph.commit
        ):
            raise RuntimeError(f"native execution or revision mismatch in {name}")
        if name == "baseline":
            if runner.native_results != native:
                raise RuntimeError("native/adapter identity or outcome mismatch")
            print("baseline: checking snapshot repeatability...", flush=True)
            repeated, _, _ = collect(repo, config, python)
            if repeated != snapshot:
                raise RuntimeError("non-repeatable inventory/graph/provenance")
            write_json(directory / "repeat.snapshot.json", repeated.model_dump())
        if proposal is not None and not actual_failed <= selected:
            raise RuntimeError("seeded regression would have been missed")
        record = {
            "scenario": name,
            "commit": snapshot.graph.commit,
            "units": len(units),
            "native_cases": len(runner.pytest_cases),
            "collection_seconds": collection_duration,
            "full_seconds": result.duration,
            "native_exit": result.returncode,
            "smartci_status": result.status,
            "failed_files": sorted(actual_failed),
            "selected_files": sorted(selected) if proposal else None,
            "fallback": proposal.fallback if proposal else [],
            "execution": "full",
        }
        records.append(record)
        write_json(
            output / "verification.json",
            {
                "native_baseline_seconds": native_duration,
                "native_identity_outcome_parity": True,
                "scenarios": records,
            },
        )
        print(
            f"{name}: proposed={len(selected) if proposal else len(units)}/{len(units)} files; execution=full; expected failures={len(actual_failed)}; fallback={record['fallback']}; collection={collection_duration:.2f}s",
            flush=True,
        )
        return snapshot

    def commit_change():
        run(["git", "add", "--all"], repo)
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE="2026-11-20T00:00:00Z",
            GIT_COMMITTER_DATE="2026-11-20T00:00:00Z",
        )
        run(
            [
                "git",
                "-c",
                "user.name=Smart CI pilot",
                "-c",
                "user.email=pilot@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Smart CI disposable acceptance scenario",
            ],
            repo,
            env=env,
        )

    def checkout(commit=REVISION):
        if current_clean_head(repo) is None:
            raise RuntimeError(
                "dirty pilot checkout retained; refusing to overwrite it"
            )
        run(["git", "checkout", "--detach", commit], repo)

    def append(path, text):
        target = repo / path
        target.write_text((target.read_text() if target.exists() else "") + text)

    license_file = "src/packaging/licenses/_spdx.py"
    licensing = {"tests/test_licenses.py", "tests/test_metadata.py"}
    dependent = licensing | {"tests/test_direct_url.py"}
    baseline = capture("baseline")
    append(license_file, '\nLICENSES.pop("mit", None)\n')
    commit_change()
    capture("license-defect", baseline, licensing, {"tests/test_metadata.py"})
    checkout()
    direct = repo / "src/packaging/direct_url.py"
    original_direct = direct.read_text()
    direct.write_text(
        original_direct.replace(
            "import dataclasses",
            "from .licenses import canonicalize_license_expression\n\nimport dataclasses",
            1,
        ).replace(
            "    return {key: value for key, value in data if value is not None}",
            '    canonicalize_license_expression("MIT")\n    return {key: value for key, value in data if value is not None}',
            1,
        )
    )
    if '    canonicalize_license_expression("MIT")' not in direct.read_text():
        raise RuntimeError("upstream mutation anchor changed")
    commit_change()
    added = capture("added-dependency", baseline, {"tests/test_direct_url.py"})
    append(license_file, '\nLICENSES.pop("mit", None)\n')
    commit_change()
    capture(
        "indirect-defect",
        added,
        dependent,
        {"tests/test_metadata.py", "tests/test_direct_url.py"},
    )
    checkout(added.graph.commit)
    direct.write_text(original_direct)
    append(license_file, "\n# Upstream change after removing the dependency.\n")
    commit_change()
    capture("removed-dependency", added, dependent)
    checkout()
    (repo / license_file).rename(repo / "src/packaging/licenses/_spdx_data.py")
    for filename in ("src/packaging/licenses/__init__.py", "tests/test_licenses.py"):
        path = repo / filename
        path.write_text(path.read_text().replace("._spdx import", "._spdx_data import"))
    commit_change()
    capture("renamed-module", baseline, licensing)
    checkout()
    append(
        "tests/test_smartci_pilot.py",
        'from packaging.licenses import canonicalize_license_expression\ndef test_added_case():\n    assert canonicalize_license_expression("MIT") == "MIT"\n',
    )
    commit_change()
    capture("new-test", baseline, {"tests/test_smartci_pilot.py"})
    checkout()
    append("pyproject.toml", "\n# Broad configuration change.\n")
    commit_change()
    capture("configuration", baseline, full_reason="ENVIRONMENT_MISMATCH")
    checkout()
    append(
        "src/packaging/_smartci_dynamic.py",
        "import importlib\ndef load(name):\n    return importlib.import_module(name)\n",
    )
    commit_change()
    capture("dynamic-import", baseline, full_reason="INCOMPLETE_EVIDENCE")
    checkout()
    # Exercise the CLI's absent-evidence fallback, with a valid head inventory.
    missing = argparse.Namespace(
        repo=repo,
        base_snapshot=output / "missing.json",
        head_snapshot=output / "baseline/snapshot.json",
        policy=EXAMPLE / "policy.json",
        output=output / "missing-base.selection.json",
        audit=output / "missing-base.audit.md",
    )
    if (
        plan_command(missing)
        or json.loads(missing.output.read_text())["execution"] != "full"
    ):
        raise RuntimeError("missing evidence did not require full execution")
    run(
        ["git", "apply", "--check", str(ROOT / "docs/onboarding/packaging.patch")], repo
    )
    write_json(
        workspace / "latest-verification.json",
        {"directory": output.name, "complete": True},
    )
    print(
        f"Verified {len(records)} full-run scenarios, snapshot repeatability, missing-evidence fallback and the reversible patch. Artifacts: {output}",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "verify"])
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace == ROOT or ROOT.is_relative_to(workspace):
        parser.error(
            "workspace must be a disposable child or a separate temporary directory"
        )
    (setup if args.command == "setup" else verify)(workspace)


if __name__ == "__main__":
    main()
