import hashlib
import importlib
import json
from pathlib import Path

import pytest
from test_observation_comparison import pair, resign, write  # noqa: F401


@pytest.fixture
def evidence(pair, monkeypatch):  # noqa: F811 - imported fixture
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "examples/textual"))
    module = importlib.import_module("assess_reads")
    observation_path = pair / "textual-observe-scoped-1/observation.json"
    observation = json.loads(observation_path.read_text())
    observation.update(tracked_blobs={"source.py": "f" * 40}, contexts={"@shared": {}})
    resign(observation)
    write(observation_path, observation)
    for mode in ("native", "observe-scoped"):
        folder = pair / f"textual-{mode}-1"
        execution = json.loads((folder / "execution.json").read_text())
        execution["source_read_provenance"] = mode == "observe-scoped"
        write(folder / "execution.json", execution)
        write(folder / "profile.json", {"packages": [["pytest", "9.2"]]})
    provenance = {
        "schema": "smartci.runtime-read-provenance.v1",
        "commit": "b" * 40,
        "observation_sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest(),
        "tracer_sha256": "e" * 64,
        "omission_authorized": False,
        "completed_protocols": 3,
        "diagnostics": [],
        "events": [
            {
                "path": "source.py",
                "context": "@shared",
                "lifecycle": "after_tests",
                "stack": [{"family": "coverage"}],
                "stack_truncated": True,
            }
        ],
    }
    resign(provenance)
    write(pair / "textual-observe-scoped-1/read-provenance.json", provenance)
    return pair, module


def test_report_reads_do_not_authorize_omissions(evidence):
    root, module = evidence
    result = module.assess(root, ["source.py"], "e" * 64)
    assert result["paths"][0]["lifecycle_counts"] == {"after_tests": 1}
    assert result["paths"][0]["stack_family_counts"] == {"coverage": 1}
    assert result["execution_required"] == "full"
    assert result["omission_authorized"] is False
    assert result["ci_savings_demonstrated"] is False


@pytest.mark.parametrize(
    "defect",
    [
        "revision",
        "observer",
        "tracer",
        "digest",
        "protocols",
        "diagnostic",
        "permission",
        "phase",
        "path",
        "external_frame",
        "profile",
        "execution",
    ],
)
def test_incomplete_misbound_and_unbounded_traces_are_rejected(evidence, defect):
    root, module = evidence
    path = root / "textual-observe-scoped-1/read-provenance.json"
    data = json.loads(path.read_text())
    if defect == "phase":
        data["events"][0]["lifecycle"] = "asserted_safe"
    elif defect == "path":
        data["events"][0]["path"] = "../outside.py"
    elif defect == "external_frame":
        data["events"][0]["stack"][0]["path"] = "/private/file.py"
    elif defect in {"profile", "execution"}:
        path = root / f"textual-native-1/{defect}.json"
        data = json.loads(path.read_text())
        data["packages" if defect == "profile" else "source_read_provenance"] = True
    else:
        key, value = {
            "revision": ("commit", "d" * 40),
            "observer": ("observation_sha256", "d" * 64),
            "tracer": ("tracer_sha256", "d" * 64),
            "digest": ("digest", "d" * 64),
            "protocols": ("completed_protocols", 2),
            "diagnostic": ("diagnostics", ["READ_PROVENANCE_LIMIT_REACHED"]),
            "permission": ("omission_authorized", True),
        }[defect]
        data[key] = value
    if defect != "digest":
        resign(data)
    write(path, data)
    with pytest.raises(ValueError):
        module.assess(root, ["source.py"], "e" * 64)
