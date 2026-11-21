import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
render = runpy.run_path(str(ROOT / "scripts/render_onrecord_ci.py"))["render"]


@pytest.mark.parametrize(
    "repository,ref",
    [
        ("owner/repo\npermissions: write-all", "a" * 40),
        ("owner/repo", "main"),
        ("owner/repo", "a" * 39),
        ("owner/repo", "a" * 40 + "\n"),
    ],
)
def test_workflow_rejects_injection_and_mutable_tool_ref(repository, ref):
    with pytest.raises(ValueError):
        render(repository, ref)


def test_workflow_has_independent_full_fallback_and_no_deployment_trigger():
    content = render("owner/smart-ci", "a" * 40)
    assert "pull_request:" in content
    assert "pull_request_target" not in content
    assert "  push:" not in content and "workflow_dispatch" not in content
    assert "id-token:" not in content and "secrets." not in content
    assert "contents: read" in content
    assert content.count("persist-credentials: false") == 3
    assert '--base "$BASE_SHA"' in content
    assert 'if [[ "$status" -eq 0 || "$status" -eq 1 ]]' in content
    assert (
        "node node_modules/vitest/vitest.mjs run --config vitest.config.ts" in content
    )
    assert "control/examples/onrecord/typescript.json" in content
    assert "SMARTCI_FORCE_FULL" in content
    assert "TOOL_COMMIT" not in content


def test_benchmark_is_opt_in_bounded_and_cannot_disable_normal_execution():
    content = render("owner/smart-ci", "a" * 40)
    normal, experiment = content.split("      # Explicit, bounded experiment only;")
    assert "SMARTCI_BENCHMARK" not in normal
    assert (
        "cache: npm" in normal
        and "cache-dependency-path: app/package-lock.json" in normal
    )
    assert "npm ci --ignore-scripts" in normal
    assert "vars.SMARTCI_BENCHMARK == 'true'" in experiment
    assert "github.head_ref == 'codex/smartci-subset-probe'" in experiment
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository"
        in experiment
    )
    assert "--rounds 3" in experiment
    assert "ref: e6b35ea089abedfd49b6ca0547a5351058d6b1ed" in experiment
