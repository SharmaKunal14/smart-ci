import os
import runpy
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
render = runpy.run_path(str(ROOT / "scripts/render_ci.py"))["render"]
ORIGINAL = (ROOT / "fixtures/packaging-test.yml").read_text()
TEMPLATE = (ROOT / "examples/onboarding/packaging/shadow-jobs.yml.in").read_text()


def test_enrollment_replaces_one_matrix_cell_and_preserves_other_jobs():
    generated = render(ORIGINAL, "owner/smartci", "a" * 40)
    assert 'os: Ubuntu\n            python_version: "3.14"' in generated
    assert "      - musl\n      - smartci-native" in generated
    assert "  workflow_dispatch:" in generated
    assert "pull_request_target" not in generated and "workflow_run:" not in generated
    assert "paths-ignore:" not in generated and "paths:" not in generated
    assert "secrets:" not in generated and "persist-credentials: true" not in generated
    # All unrelated upstream jobs, commands and checks are retained byte for byte.
    for name, following in [
        ("musl", "property-tests"),
        ("property-tests", "downstream"),
    ]:
        block = ORIGINAL.split(f"  {name}:\n", 1)[1].split(f"  {following}:\n", 1)[0]
        assert block in generated
    assert (
        generated.count('"$RUNNER_TEMP/native/bin/python" -m coverage run -m pytest')
        == 1
    )
    assert generated.index("name: smartci-proposal-") < generated.index(
        "Native full suite"
    )
    native_job = generated.split("  smartci-native:", 1)[1].split(
        "  smartci-publish:", 1
    )[0]
    assert "if: ${{ always() && !cancelled() }}" in native_job
    assert "fetch-depth: 0" in native_job
    assert "GH_TOKEN" not in native_job and "actions: write" not in generated
    native_step = native_job.split("- name: Native full suite", 1)[1].split(
        "- name: Compare", 1
    )[0]
    assert "if:" not in native_step and "continue-on-error" not in native_step
    assert "github.event_name == 'push' && github.ref_protected" in generated


@pytest.mark.parametrize(
    "repo,sha",
    [
        ("owner/repo;evil", "a" * 40),
        ("owner/repo", "main"),
        ("../owner/repo", "a" * 40),
    ],
)
def test_workflow_rejects_unpinned_or_injected_tool_source(repo, sha):
    with pytest.raises(ValueError):
        render(ORIGINAL, repo, sha)


def test_workflow_drift_requires_review():
    with pytest.raises(ValueError):
        render(ORIGINAL + "\n", "owner/repo", "a" * 40)


@pytest.mark.parametrize("observer", ["success", "failure", "skipped"])
@pytest.mark.parametrize("native_exit", [0, 1, 5])
def test_native_step_runs_once_and_propagates_failure_independently_of_observer(
    tmp_path, observer, native_exit
):
    block = TEMPLATE.split("- name: Native full suite", 1)[1].split(
        "      - name: Compare", 1
    )[0]
    script = textwrap.dedent(block.split("        run: |\n", 1)[1])
    python = tmp_path / "native/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        '#!/bin/bash\nif [ "$3" = run ]; then\n echo full >> "$RUNNER_TEMP/calls"\n exit "$TEST_EXIT"\nfi\nexit 0\n'
    )
    python.chmod(0o755)
    actual = subprocess.run(
        ["bash", "-e", "-c", script],
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
            "OBSERVER_READY": observer,
            "TEST_EXIT": str(native_exit),
        },
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert actual.returncode == native_exit
    assert (tmp_path / "calls").read_text() == "full\n"
    assert (tmp_path / "outputs").read_text() == f"exit={native_exit}\n"
