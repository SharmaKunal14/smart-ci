import copy
import json
import sys

import pytest
from test_bazel_bundle import capture, capture_events, git  # noqa: F401

from smartci.bazel.audit import NativeInventory
from smartci.bazel.bundle import canonical, pack
from smartci.bazel.collection import CaptureCommand
from smartci.bazel.execution import ExecutionConfig, execute, reconcile_execution
from smartci.cli import main


def evidence(*, subset=False, failure=False, extra=False):
    rows = capture_events()
    if extra:
        built = copy.deepcopy(rows[2])
        built["id"]["targetCompleted"]["label"] = "//lib:new_binary"
        built["children"] = []
        rows[0]["children"].append(built["id"])
        rows.insert(-2, built)
    if subset:
        for row in rows:
            if "pattern" in row["id"]:
                row["id"]["pattern"]["pattern"] = ["...", "-//lib:b_test"]
        rows[0]["children"][0]["pattern"]["pattern"] = ["...", "-//lib:b_test"]

        def omitted(identifier):
            return any(
                identifier.get(kind, {}).get("label") == "//lib:b_test"
                for kind in ("targetCompleted", "testSummary")
            )

        rows = [row for row in rows if not omitted(row["id"])]
        for row in rows:
            if "children" in row:
                row["children"] = [c for c in row["children"] if not omitted(c)]
    if failure:
        rows = [
            row
            for row in rows
            if row["id"] != {"testSummary": {"label": "//lib:a_test"}}
        ]
        for row in rows:
            if row["id"].get("targetCompleted", {}).get("label") == "//lib:a_test":
                row["completed"]["success"] = False
                row["children"] = []
            if "finished" in row:
                row["finished"]["exitCode"]["code"] = 1
    return b"".join(canonical(row) for row in rows)


@pytest.fixture
def execution_case(tmp_path, request):
    repo, base, profile, artifacts = request.getfixturevalue("capture")
    bundle_path = tmp_path / "bundle"
    bundle = pack(bundle_path, profile, base, artifacts)
    (repo / "lib/a.h").write_text("ordinary implementation change\n")
    git(repo, "add", ".")
    git(repo, "commit", "--no-gpg-sign", "-qm", "change a")
    head = git(repo, "rev-parse", "HEAD")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    driver = inputs / "driver.py"
    driver.write_text("""import os,sys,time
from pathlib import Path
stage,inputs,capture,defect=sys.argv[1:]
inputs,capture=Path(inputs),Path(capture)
assert 'GH_TOKEN' not in os.environ and 'OPENAI_API_KEY' not in os.environ
(inputs/(stage+'.called')).write_text('called')
if defect == 'timeout': time.sleep(30)
if defect == 'dirty': Path('lib/a.h').write_text('uncommitted mutation')
(capture/'native.bep.json').write_bytes((inputs/(stage+'.bep')).read_bytes())
raise SystemExit(1 if defect == 'failure' else 0)
""")
    (inputs / "full.bep").write_bytes(evidence())
    (inputs / "subset.bep").write_bytes(evidence(subset=True))

    def config(defect="none"):
        return ExecutionConfig(
            schema_version="1",
            profile=profile,
            subset_options_digest=profile.options_digest,
            **{
                stage: CaptureCommand(
                    argv=[
                        sys.executable,
                        str(driver),
                        stage,
                        str(inputs),
                        "{capture}",
                        defect,
                    ],
                    timeout_seconds=1 if defect == "timeout" else 10,
                )
                for stage in ("full", "subset")
            },
        )

    return repo, base, head, config, bundle_path, bundle.manifest_digest, inputs


def run_case(tmp_path, case, *, defect="none", bundle=True, force=False):
    repo, base, head, config, path, digest, _ = case
    return execute(
        repo,
        base,
        head,
        config(defect),
        tmp_path / "out",
        bundle_path=path if bundle else None,
        expected_digest=digest if bundle else None,
        force_full=force,
    )


def test_selective_execution_uses_actual_map_and_preserves_native_build_only_scope(
    tmp_path, execution_case, monkeypatch
):
    monkeypatch.setenv("GH_TOKEN", "do-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    report = run_case(tmp_path, execution_case)
    inputs = execution_case[-1]
    assert report["status"] == "passed" and report["mode"] == "subset"
    assert report["bazel"]["test_targets"] == {"//lib:a_test": "PASSED"}
    assert report["bazel"]["build_target_configuration_count"] == 2
    assert (inputs / "subset.called").exists() and not (inputs / "full.called").exists()
    plan = json.loads((tmp_path / "out/plan.json").read_bytes())
    assert plan["selected"] == ["//lib:a_test"] and plan["build_only"] == [
        "//lib:binary"
    ]
    assert (
        plan["production_omission_authorized"]
        and not plan["requires_independent_full_control"]
    )


@pytest.mark.parametrize("mode", ["missing", "tampered", "force", "risk"])
def test_unproven_subset_or_force_full_runs_independent_native_command(
    tmp_path, execution_case, mode
):
    case = list(execution_case)
    if mode == "tampered":
        (case[4] / "query.xml").write_text("tampered")
    if mode == "risk":
        (case[0] / "MODULE.bazel").write_text("dependency update")
        git(case[0], "add", ".")
        git(case[0], "commit", "--no-gpg-sign", "-qm", "risk")
        case[2] = git(case[0], "rev-parse", "HEAD")
    report = run_case(tmp_path, case, bundle=mode != "missing", force=mode == "force")
    assert report["status"] == "passed" and report["mode"] == "full"
    assert report["bazel"]["test_target_count"] == 2
    assert (case[-1] / "full.called").exists() and not (
        case[-1] / "subset.called"
    ).exists()
    assert json.loads((tmp_path / "out/plan.json").read_bytes())["patterns"] == ["..."]


def test_full_fallback_can_discover_new_native_targets_without_old_inventory(
    tmp_path, execution_case
):
    (execution_case[-1] / "full.bep").write_bytes(evidence(extra=True))
    report = run_case(tmp_path, execution_case, bundle=False)
    assert (
        report["status"] == "passed"
        and report["bazel"]["build_target_configuration_count"] == 4
    )


def test_compiler_failure_remains_failed_and_accounts_for_unexecuted_test(
    tmp_path, execution_case
):
    (execution_case[-1] / "subset.bep").write_bytes(evidence(subset=True, failure=True))
    report = run_case(tmp_path, execution_case, defect="failure")
    assert (
        report["status"] == "failed"
        and report["exit_code"] == 1
        and report["error"] is None
    )
    assert report["bazel"]["test_target_count"] == 0
    assert report["failed_build_targets"] == ["//lib:a_test"]
    assert not (execution_case[-1] / "full.called").exists()


@pytest.mark.parametrize("defect", ["dirty", "timeout"])
def test_timeout_or_source_mutation_cannot_pass(tmp_path, execution_case, defect):
    report = run_case(tmp_path, execution_case, defect=defect)
    assert report["status"] == "failed" and report["error"]


def test_wrong_checkout_rejected_before_any_command(tmp_path, execution_case):
    (execution_case[0] / "lib/a.h").write_text("uncommitted")
    with pytest.raises(ValueError):
        run_case(tmp_path, execution_case)
    assert not (execution_case[-1] / "subset.called").exists()
    assert not (execution_case[-1] / "full.called").exists()


@pytest.mark.parametrize(
    "defect",
    [
        "unexpected_test",
        "build_only",
        "configuration",
        "patterns",
        "version",
        "options",
        "incomplete",
        "flaky",
        "exit",
        "false_pass",
    ],
)
def test_execution_reconciliation_rejects_scope_profile_and_evidence_mismatches(
    request, defect
):
    profile = request.getfixturevalue("capture")[2]
    rows = [json.loads(line) for line in evidence(subset=True).splitlines()]
    if defect == "unexpected_test":
        rows = [json.loads(line) for line in evidence().splitlines()]
    if defect == "build_only":
        rows = [r for r in rows if "//lib:binary" not in json.dumps(r["id"])]
        rows[0]["children"] = [
            c for c in rows[0]["children"] if "//lib:binary" not in json.dumps(c)
        ]
    if defect == "configuration":
        for row in rows:
            if "targetCompleted" in row["id"]:
                row["id"]["targetCompleted"]["configuration"]["id"] = "b" * 64
    if defect == "patterns":
        rows[1]["id"]["pattern"]["pattern"] = ["..."]
    if defect == "version":
        rows[0]["started"]["buildToolVersion"] = "10.0.0"
    if defect == "options":
        rows[0]["started"]["optionsDescription"] = "different"
    if defect == "incomplete":
        rows.pop()
    if defect == "flaky":
        for row in rows:
            if "testSummary" in row:
                row["testSummary"]["overallStatus"] = "FLAKY"
    if defect == "false_pass":
        for row in rows:
            if "completed" in row:
                row["completed"]["success"] = False
    raw = b"".join(canonical(row) for row in rows)
    expected = NativeInventory(
        {"//lib:a_test": ("a" * 64,), "//lib:binary": ("a" * 64,)}, ("//lib:a_test",)
    )
    with pytest.raises(ValueError):
        reconcile_execution(
            raw,
            3 if defect == "exit" else 0,
            profile,
            ["...", "-//lib:b_test"],
            expected,
        )


def test_cli_schema_and_native_failure_exit(
    tmp_path, execution_case, capsys, monkeypatch
):
    repo, base, head, config, path, digest, inputs = execution_case
    config_path = tmp_path / "execution.json"
    config_path.write_bytes(canonical(config("failure").model_dump()))
    (inputs / "subset.bep").write_bytes(evidence(subset=True, failure=True))
    monkeypatch.setattr(sys, "argv", ["smartci", "schema", "bazel-execution"])
    assert main() == 0
    assert "subset_options_digest" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartci",
            "bazel",
            "execute",
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--config",
            str(config_path),
            "--bundle",
            str(path),
            "--expected-digest",
            digest,
            "--output",
            str(tmp_path / "out"),
        ],
    )
    assert main() == 1
