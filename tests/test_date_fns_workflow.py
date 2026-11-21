import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
render = runpy.run_path(str(ROOT / "scripts/render_date_fns_ci.py"))["render"]


@pytest.mark.parametrize(
    "repository,ref",
    [
        ("owner/repo\npermissions: write-all", "a" * 40),
        ("owner/repo", "main"),
        ("owner/repo", "a" * 40 + "\n"),
    ],
)
def test_evaluation_requires_safe_repository_and_immutable_pin(repository, ref):
    with pytest.raises(ValueError):
        render(repository, ref)


def test_native_control_remains_authoritative_and_workflow_is_bounded():
    content = render("owner/smart-ci", "a" * 40)
    assert "pull_request:" in content and "pull_request_target" not in content
    assert "contents: read" in content and "timeout-minutes: 15" in content
    assert "secrets." not in content and "id-token:" not in content
    assert content.count("persist-credentials: false") == 2
    assert '--base "$BASE_SHA"' in content and "--frozen-lockfile" in content
    assert 'if [[ "$status" -eq 0 || "$status" -eq 1 ]]' in content
    assert (
        'test "$NATIVE" = success && test "$TIMEZONE" = success && test "$SMARTCI" = success'
        in content
    )
    assert "bash scripts/test/tz.sh" in content
    assert "--maxWorkers" not in content and "--no-isolate" not in content
    assert "retention-days: 3" in content and "TOOL_COMMIT" not in content
