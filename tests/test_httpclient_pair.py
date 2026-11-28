"""A paired benchmark must not inherit live services from its preceding arm."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "httpclient_pair",
    Path(__file__).resolve().parents[1] / "examples/httpclient/paired.py",
)
pair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pair)


def test_native_cleanup_is_awaited_and_charged_to_owning_arm(tmp_path, monkeypatch):
    states = iter(['{"Image":"testcontainers/ryuk","ID":"native-reaper"}\n', ""])
    clock = iter([0.0, 1.0, 6.0])
    monkeypatch.setattr(pair.subprocess, "check_output", lambda *a, **k: next(states))
    monkeypatch.setattr(pair.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pair.time, "sleep", lambda _: None)
    pair.settle_containers(tmp_path)
    report = json.loads((tmp_path / "container-cleanup.json").read_text())
    assert report["settled"] and report["seconds"] == 6
    assert report["observations"][0]["containers"][0]["ID"] == "native-reaper"


def test_persistent_container_stops_comparison_instead_of_forcing_independence(
    tmp_path, monkeypatch
):
    clock = iter([0.0, 46.0])
    monkeypatch.setattr(
        pair.subprocess, "check_output", lambda *a, **k: '{"ID":"still-active"}\n'
    )
    monkeypatch.setattr(pair.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="remain active"):
        pair.settle_containers(tmp_path)
    assert (
        json.loads((tmp_path / "container-cleanup.json").read_text())["settled"]
        is False
    )
