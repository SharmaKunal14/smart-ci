import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import test_discovery
from pydantic import ValidationError
from test_discovery import commit, config, environment, policy

from smartci.adapters.runners import PyReport
from smartci.ci.commands import github_context, prepare
from smartci.ci.github import download_baseline
from smartci.ci.models import Baseline, Context, ExpectedSkip, ShadowPolicy
from smartci.ci.shadow import compare, validate_baseline
from smartci.discovery.collector import collect
from smartci.discovery.models import Snapshot
from smartci.selection import digest, fallback, finish

repository = test_discovery.repository


def context(**changes):
    data = {
        "repository": "example/python",
        "event": "push",
        "run_id": 10,
        "run_attempt": 1,
        "base": "a" * 40,
        "tested": "a" * 40,
        "ref": "refs/heads/main",
        "default_branch": "main",
        "protected": True,
    }
    data.update(changes)
    return Context.model_validate(data)


@pytest.fixture
def evidence(monkeypatch):
    env = environment().model_copy(update={"platform": "Linux"})
    path = "tests/test_app.py"
    case = path + "::test_app"
    data = {
        "schema_version": "1",
        "repository": "example/python",
        "graph": {
            "schema_version": "1",
            "repository": "example/python",
            "commit": "a" * 40,
            "complete": True,
            "unsupported": False,
            "owners": {path: "test"},
            "dependencies": {"test": []},
            "tests": {"test": "test"},
        },
        "inventory": {
            "schema_version": "1",
            "repository": "example/python",
            "complete": True,
            "environment": env.identity(),
            "tests": [
                {"id": "test", "runner": "pytest", "granularity": "file", "path": path}
            ],
        },
        "provenance": {
            "implementation_digest": "0" * 64,
            "config": config().model_dump(),
            "environment": env.model_dump(),
            "sources": {path: "b" * 64},
            "native_targets": {"test": path},
            "native_cases_digest": digest([case]),
            "native_case_count": 1,
            "plugins": [],
            "edges": [],
            "imports": [],
            "gaps": [],
        },
    }
    # Include defaults before signing, as the production collector does.
    from smartci.discovery.models import Provenance

    data["provenance"] = Provenance.model_validate(data["provenance"]).model_dump()
    data["digest"] = digest(data)
    snapshot = Snapshot.model_validate(data)
    decision = fallback("FIRST_RUN", snapshot.inventory)
    decision.comparison = {"base": "a" * 40, "head": "a" * 40}
    decision.evidence = {"head_snapshot": snapshot.digest}
    finish(decision)
    native = PyReport(collected=[case], results={case: "passed"}, exit=0)
    monkeypatch.setattr("smartci.ci.shadow.current_clean_head", lambda root: "a" * 40)
    return snapshot, decision, native


def result(evidence, **kwargs):
    snapshot, decision, native = evidence
    return compare(
        kwargs.get("ctx", context()),
        snapshot,
        decision,
        native,
        kwargs.get("exit", native.exit),
        kwargs.get("rules", ShadowPolicy()),
        Path("."),
    )


def baseline(evidence):
    return Baseline(
        context=context(),
        snapshot=evidence[0],
        comparison=result(evidence),
        policy_digest="c" * 64,
        created_at=100,
        expires_at=200,
    )


def test_complete_protected_linux_baseline(evidence):
    assert result(evidence).baseline_eligible
    assert (
        validate_baseline(baseline(evidence), context(), "c" * 64, 101, 100)
        == evidence[0]
    )


@pytest.mark.parametrize(
    "name", ["../repo", "owner/..", "owner/.", "owner/repo?x=1", "owner/repo/extra"]
)
def test_repository_route_components_are_constrained(name):
    with pytest.raises(ValidationError):
        context(repository=name)


@pytest.mark.parametrize(
    "response", [b"[]", b"null", b'{"name":"main","protected":true,"unused":0}']
)
def test_invalid_api_shapes_fail_with_safe_input_error(response):
    with pytest.raises((ValueError, TypeError)):
        download_baseline(
            context(), ".github/workflows/test.yml", lambda route: response
        )


@pytest.mark.parametrize(
    "change", [{"python": "3.15.0"}, {"implementation": "PyPy"}, {"platform": "Darwin"}]
)
def test_other_runtime_profiles_are_not_baseline_eligible(evidence, change):
    from smartci.discovery.models import Environment

    snapshot, decision, native = evidence
    data = snapshot.model_dump()
    data["provenance"]["environment"].update(change)
    data["inventory"]["environment"] = Environment.model_validate(
        data["provenance"]["environment"]
    ).identity()
    data["digest"] = digest({k: v for k, v in data.items() if k != "digest"})
    snapshot = Snapshot.model_validate(data)
    decision.evidence["head_snapshot"] = snapshot.digest
    finish(decision)
    actual = result((snapshot, decision, native))
    assert actual.status == "complete" and not actual.baseline_eligible


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "plugin",
        "wrong_exit",
        "wrong_revision",
        "digest",
        "selected",
        "comparison",
        "skip",
    ],
)
def test_incomplete_evidence_cannot_promote(evidence, change):
    snapshot, decision, native = evidence
    if change == "missing":
        native.results = {}
    if change == "duplicate":
        native.collected *= 2
    if change == "plugin":
        native.plugins = ["unexpected"]
    if change == "wrong_exit":
        native.exit = 5
    if change == "wrong_revision":
        snapshot.graph.commit = "b" * 40
    if change == "digest":
        decision.digest = "0" * 64
    if change == "selected":
        decision.selected = []
        finish(decision)
    if change == "comparison":
        decision.comparison["base"] = "b" * 40
        finish(decision)
    if change == "skip":
        native.results[native.collected[0]] = "skipped"
    actual = result(evidence)
    assert actual.status == "incomplete"
    assert not actual.baseline_eligible


@pytest.mark.parametrize("mismatch", [None, "platform", "reason", "source", "xfail"])
def test_reviewed_skip_explained_without_becoming_promotion_baseline(
    evidence, mismatch
):
    _snapshot, _, native = evidence
    case = native.collected[0]
    native.results[case] = "skipped"
    native.skip_reasons[case] = "requires a glibc-based Linux"
    rule = ExpectedSkip(
        case=case,
        platform="Linux",
        reason=native.skip_reasons[case],
        source_digest="b" * 64,
    )
    if mismatch == "platform":
        rule.platform = "Darwin"
    if mismatch == "reason":
        rule.reason = "another reason"
    if mismatch == "source":
        rule.source_digest = "a" * 64
    if mismatch == "xfail":
        native.skip_reasons = {}
    actual = result(evidence, rules=ShadowPolicy(expected_skips=[rule]))
    assert actual.status == (
        "incomplete" if mismatch else "complete_with_expected_skips"
    )
    assert not actual.baseline_eligible


def test_failed_omitted_test_is_visible(evidence):
    _snapshot, decision, native = evidence
    decision.mode = "subset"
    decision.selected = []
    decision.omitted = {"test": "TEST_ONLY_COUNTEREXAMPLE"}
    finish(decision)
    native.results[native.collected[0]] = "failed"
    native.exit = 1
    actual = result(evidence)
    assert actual.status == "failed"
    assert actual.missed_failure_files == ["tests/test_app.py"]
    assert not actual.baseline_eligible


@pytest.mark.parametrize(
    "change",
    ["expired", "future", "policy", "base", "repo", "unprotected", "pr", "darwin"],
)
def test_baseline_trust_boundaries(evidence, change):
    saved = baseline(evidence)
    ctx, now, policy_hash = context(), 101, "c" * 64
    if change == "expired":
        now = 200
    if change == "future":
        now = 99
    if change == "policy":
        policy_hash = "d" * 64
    if change == "base":
        ctx.base = "b" * 40
    if change == "repo":
        ctx.repository = "other/repo"
    if change in {"unprotected", "pr", "darwin"}:
        data = saved.model_dump()
        if change == "unprotected":
            data["context"]["protected"] = False
        if change == "pr":
            data["context"]["event"] = "pull_request"
        if change == "darwin":
            data["snapshot"]["provenance"]["environment"]["platform"] = "Darwin"
        with pytest.raises(ValidationError):
            Baseline.model_validate(data)
    else:
        with pytest.raises(ValueError):
            validate_baseline(saved, ctx, policy_hash, now, 100)


def responses(saved, *, mutation=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "../baseline.json" if mutation == "path" else "baseline.json",
            saved.model_dump_json(),
        )
    raw = buf.getvalue()
    run = {
        "id": 10,
        "run_attempt": 1,
        "event": "push",
        "conclusion": "success",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "path": ".github/workflows/test.yml",
        "repository": {"full_name": "example/python"},
        "head_repository": {"full_name": "example/python"},
    }
    artifact = {
        "id": 20,
        "name": "smartci-baseline-linux-py314-1",
        "expired": False,
        "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    if mutation == "fork":
        run["head_repository"]["full_name"] = "attacker/python"
    if mutation == "event":
        run["event"] = "pull_request"
    if mutation == "workflow":
        run["path"] = ".github/workflows/other.yml"
    if mutation == "attempt":
        run["run_attempt"] = 2
    if mutation == "digest":
        artifact["digest"] = "sha256:" + "0" * 64
    if mutation == "expired":
        artifact["expired"] = True
    if mutation == "oversize":
        artifact["size_in_bytes"] = 99_000_000

    def request(route):
        if "/branches/" in route:
            return json.dumps(
                {"name": "main", "protected": mutation != "unprotected"}
            ).encode()
        if "/workflows/" in route:
            return json.dumps({"workflow_runs": [run]}).encode()
        if route.endswith("/zip"):
            return raw
        return json.dumps(
            {
                "artifacts": [artifact, artifact]
                if mutation == "duplicate"
                else [artifact]
            }
        ).encode()

    return request


def test_download_provenance_and_payload(evidence):
    saved = baseline(evidence)
    assert (
        download_baseline(context(), ".github/workflows/test.yml", responses(saved))
        == saved
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "path",
        "fork",
        "event",
        "workflow",
        "attempt",
        "digest",
        "expired",
        "oversize",
        "unprotected",
        "duplicate",
    ],
)
def test_reject_untrusted_artifact(evidence, mutation):
    with pytest.raises(ValueError):
        download_baseline(
            context(),
            ".github/workflows/test.yml",
            responses(baseline(evidence), mutation=mutation),
        )


def test_pr_context_records_tested_merge_and_distinct_pr_head(tmp_path, monkeypatch):
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps(
            {
                "pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}},
                "repository": {"default_branch": "main"},
            }
        )
    )
    values = {
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": "example/python",
        "GITHUB_SHA": "c" * 40,
        "GITHUB_RUN_ID": "1",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_REF": "refs/pull/1/merge",
        "GITHUB_REF_PROTECTED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    actual = github_context()
    assert (
        actual.base == "a" * 40
        and actual.pr_head == "b" * 40
        and actual.tested == "c" * 40
    )
    assert actual.run_attempt == 2 and not actual.protected


def test_real_prepare_repeatability_full_fallback_and_native_skip_observer(
    repository, tmp_path
):
    snapshot, _, _ = collect(repository, config(), sys.executable)
    ctx = context(base=snapshot.graph.commit, tested=snapshot.graph.commit)
    cfg = tmp_path / "config.json"
    cfg.write_text(config().model_dump_json())
    reports = []
    for index in range(2):
        args = argparse.Namespace(
            output=tmp_path / str(index),
            repo=repository,
            python=sys.executable,
            config=cfg,
            baseline=None,
            force_full=False,
        )
        assert prepare(args, ctx, policy(), ShadowPolicy(), "c" * 64, 100) == 0
        reports.append(json.loads((args.output / "selection.json").read_text()))
    assert reports[0] == reports[1]
    assert reports[0]["execution"] == "full"
    assert reports[0]["fallback"] == ["BASELINE_UNAVAILABLE_OR_INCOMPATIBLE"]
    (repository / "tests/test_skip.py").write_text(
        "import pytest\ndef test_skip(): pytest.skip('reviewed platform reason')\n@pytest.mark.xfail(reason='not a platform skip')\ndef test_xfail(): assert False\n"
    )
    commit(repository)
    report = tmp_path / "native.json"
    import os

    native = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "smartci.adapters.pytest_plugin", "-q"],
        cwd=repository,
        env={**os.environ, "SMARTCI_REPORT": str(report)},
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0
    result = PyReport.model_validate_json(report.read_bytes())
    assert result.skip_reasons == {
        "tests/test_skip.py::test_skip": "reviewed platform reason"
    }


def test_collector_crash_and_force_full(evidence, tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(config().model_dump_json())
    args = argparse.Namespace(
        output=tmp_path / "out",
        repo=tmp_path / "repo",
        python=sys.executable,
        config=cfg,
        baseline=None,
        force_full=True,
    )
    monkeypatch.setattr(
        "smartci.ci.commands.collect", lambda *a: (evidence[0], None, None)
    )
    assert prepare(args, context(), policy(), ShadowPolicy(), "c" * 64, 100) == 0
    assert json.loads((args.output / "selection.json").read_text())["fallback"] == [
        "FORCE_FULL"
    ]
    args.output = tmp_path / "crashed"

    def crash(*args):
        raise ValueError("collection failed")

    monkeypatch.setattr("smartci.ci.commands.collect", crash)
    assert prepare(args, context(), policy(), ShadowPolicy(), "c" * 64, 100) == 0
    actual = json.loads((args.output / "selection.json").read_text())
    assert (
        actual["fallback"] == ["COLLECTION_UNAVAILABLE"]
        and actual["execution"] == "full"
    )


def test_compatible_baseline_drives_repeatable_pr_subset(
    repository, tmp_path, monkeypatch
):
    """Real Git/import discovery; Linux identity is a simulated unit-test input."""

    def linux(snapshot):
        data = snapshot.model_dump()
        data["provenance"]["environment"]["platform"] = "Linux"
        from smartci.discovery.models import Environment

        data["inventory"]["environment"] = Environment.model_validate(
            data["provenance"]["environment"]
        ).identity()
        data["digest"] = digest({k: v for k, v in data.items() if k != "digest"})
        return Snapshot.model_validate(data)

    base, runner, units = collect(repository, config(), sys.executable)
    assert runner.run(units).status == "passed"
    base = linux(base)
    base_context = context(base=base.graph.commit, tested=base.graph.commit)
    decision = fallback("FIRST_RUN", base.inventory)
    decision.comparison = {"base": base.graph.commit, "head": base.graph.commit}
    decision.evidence["head_snapshot"] = base.digest
    finish(decision)
    native = PyReport(
        collected=list(runner.pytest_cases),
        results=runner.native_results,
        exit=0,
        plugins=list(runner.pytest_plugins),
    )
    comparison = compare(
        base_context, base, decision, native, 0, ShadowPolicy(), repository
    )
    saved = Baseline(
        context=base_context,
        snapshot=base,
        comparison=comparison,
        policy_digest="c" * 64,
        created_at=100,
        expires_at=200,
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(saved.model_dump_json())
    (repository / "app/auth.py").write_text("def allowed():\n    return False\n")
    sha = commit(repository)
    head, _, _ = collect(repository, config(), sys.executable)
    head = linux(head)
    monkeypatch.setattr("smartci.ci.commands.collect", lambda *args: (head, None, None))
    cfg = tmp_path / "config.json"
    cfg.write_text(config().model_dump_json())
    ctx = context(
        event="pull_request",
        base=base.graph.commit,
        tested=sha,
        pr_head=sha,
        protected=False,
        ref="refs/pull/1/merge",
    )
    reports = []
    for index in range(2):
        args = argparse.Namespace(
            output=tmp_path / f"pr-{index}",
            repo=repository,
            python=sys.executable,
            config=cfg,
            baseline=baseline_path,
            force_full=False,
        )
        prepare(args, ctx, policy(), ShadowPolicy(), "c" * 64, 101)
        reports.append(json.loads((args.output / "selection.json").read_text()))
    assert reports[0] == reports[1]
    assert reports[0]["mode"] == "subset" and reports[0]["execution"] == "full"
    assert {t.path for t in head.inventory.tests if t.id in reports[0]["selected"]} == {
        "tests/test_auth.py",
        "tests/test_checkout.py",
    }
    assert not reports[0]["fallback"]
