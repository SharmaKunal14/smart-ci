import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartci.cli import InputError, validate_file
from smartci.contracts import (
    CONTRACTS,
    Execution,
    Inventory,
    Investigation,
    Policy,
    ToolRequest,
)
from smartci.provider import FixtureProvider


def inventory():
    return {
        "schema_version": "1",
        "repository": "example/repo",
        "complete": True,
        "environment": "a" * 64,
        "tests": [
            {
                "id": "example/repo:test",
                "runner": "pytest",
                "granularity": "case",
                "path": "tests/test_auth.py",
            }
        ],
    }


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", "a/../b", "a//b", "a\\b", "C:/file", "a\x00b"]
)
def test_unsafe_paths(path):
    data = inventory()
    data["tests"][0]["path"] = path
    with pytest.raises(ValidationError):
        Inventory.model_validate(data)


def test_unknown_version_duplicates_and_coercion():
    for field, value in [
        ("schema_version", "2"),
        ("complete", "true"),
        ("extra", "secret"),
    ]:
        with pytest.raises(ValidationError):
            Inventory.model_validate(inventory() | {field: value})
    data = inventory()
    data["tests"] *= 2
    with pytest.raises(ValidationError):
        Inventory.model_validate(data)


def test_policy_and_execution_safety():
    base = {"schema_version": "1", "repository": "example/repo"}
    with pytest.raises(ValidationError):
        Policy.model_validate(base | {"unknown_evidence": "skip"})
    with pytest.raises(ValidationError):
        Execution.model_validate(
            base
            | {"status": "incomplete", "outcome": "passed", "decision_digest": "a" * 64}
        )


def test_file_limits_and_redaction(tmp_path, monkeypatch, capsys):
    path = tmp_path / "input.json"
    path.write_text('{"secret":"DO_NOT_ECHO"}')
    from smartci.cli import main

    monkeypatch.setattr(sys, "argv", ["smartci", "validate", "inventory", str(path)])
    assert main() == 2
    assert "DO_NOT_ECHO" not in capsys.readouterr().out
    monkeypatch.setattr("smartci.cli.MAX_BYTES", 3)
    with pytest.raises(InputError):
        validate_file("inventory", path)
    with pytest.raises(InputError):
        validate_file("inventory", tmp_path / "missing")


def test_fixture_provider_is_offline():
    request = Investigation(
        schema_version="1",
        repository="example/repo",
        baseline_digest="a" * 64,
        max_calls=4,
        max_input_tokens=100,
        max_output_tokens=100,
    )
    response = ToolRequest(
        schema_version="1",
        repository="example/repo",
        tool="query_dependencies",
        target="auth",
        call_id="step1",
    )
    provider = FixtureProvider(response)
    assert provider.next_action(request) == response
    assert provider.next_action(request) is not response
    with pytest.raises(ValueError):
        provider.next_action(request.model_copy(update={"repository": "other/repo"}))


def test_exported_schemas_match_models():
    for name, model in CONTRACTS.items():
        assert (
            json.loads(Path(f"schemas/{name}.v1.json").read_text())
            == model.model_json_schema()
        )


def test_cli_help_and_fixture():
    result = subprocess.run(
        ["smartci", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    validate_file("inventory", Path("fixtures/inventory.valid.json"))
    with pytest.raises(InputError):
        validate_file("policy", Path("fixtures/policy.invalid.json"))
