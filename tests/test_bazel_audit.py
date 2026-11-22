import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from smartci.bazel.audit import native_inventory, reconcile_graph
from smartci.bazel.graph import QueryError, parse_query_xml

GRAPH = b"""<query>
<source-file name="//lib:main.cc"/>
<rule class="cc_library" name="//lib:main"><rule-input name="//lib:main.cc"/></rule>
<rule class="cc_test" name="//lib:test"><rule-input name="//lib:main"/></rule>
<rule class="cc_test" name="//lib:benchmark"><rule-input name="//lib:main"/></rule>
<rule class="cc_test" name="//lib:manual_test"><rule-input name="//lib:main"/></rule>
</query>"""
ROOTS = ["//lib:main", "//lib:test", "//lib:benchmark", "//lib:manual_test"]


def reference():
    return {
        "complete_stream": True,
        "exit_code": 0,
        "build_target_configuration_count": 3,
        "failed_build_target_configuration_count": 0,
        "build_target_results": {
            json.dumps(
                {"targetCompleted": {"label": name, "configuration": {"id": "a" * 64}}}
            ): True
            for name in ROOTS[:3]
        },
        "test_target_count": 1,
        "test_targets": {"//lib:test": "PASSED"},
    }


def test_native_inventory_preserves_nonexecuted_test_rules_and_build_checks():
    inventory = native_inventory(reference())
    assert inventory.tests == ("//lib:test",)
    assert inventory.build_only == ("//lib:benchmark", "//lib:main")
    result = reconcile_graph(parse_query_xml(GRAPH), ROOTS, inventory)
    assert result["query_test_rules_not_natively_executed"] == [
        "//lib:benchmark",
        "//lib:manual_test",
    ]
    assert result["query_roots_not_natively_built"] == ["//lib:manual_test"]
    assert result["omission_authorized"] is False
    assert result == reconcile_graph(
        parse_query_xml(GRAPH), list(reversed(ROOTS)), inventory
    )


@pytest.mark.parametrize(
    "defect",
    [
        "incomplete",
        "failed",
        "flaky",
        "missing_build",
        "bad_count",
        "unsafe_label",
        "aspect",
        "duplicate_configuration",
        "numeric_success",
    ],
)
def test_invalid_native_reference_never_becomes_inventory(defect):
    value = reference()
    if defect == "incomplete":
        value["complete_stream"] = False
    elif defect == "failed":
        value["exit_code"] = 3
    elif defect == "flaky":
        value["test_targets"]["//lib:test"] = "FLAKY"
    elif defect == "missing_build":
        value["test_targets"] = {"//lib:manual_test": "PASSED"}
    elif defect == "bad_count":
        value["build_target_configuration_count"] = 4
    elif defect == "numeric_success":
        value["complete_stream"] = 1
    else:
        first = next(iter(value["build_target_results"]))
        identifier = json.loads(first)
        if defect == "unsafe_label":
            identifier["targetCompleted"]["label"] = "//lib:../../escape"
        elif defect == "aspect":
            identifier["targetCompleted"]["aspect"] = "unknown"
        if defect == "duplicate_configuration":
            key = json.dumps(identifier, indent=2)
            value["build_target_configuration_count"] += 1
        else:
            del value["build_target_results"][first]
            key = json.dumps(identifier)
        value["build_target_results"][key] = True
    with pytest.raises(QueryError):
        native_inventory(value)


def test_native_configurations_are_retained_without_conflating_targets():
    value = reference()
    key = {
        "targetCompleted": {"label": "//lib:main", "configuration": {"id": "b" * 64}}
    }
    value["build_target_results"][json.dumps(key)] = True
    value["build_target_configuration_count"] += 1
    result = native_inventory(value)
    assert result.build_configurations["//lib:main"] == ("a" * 64, "b" * 64)
    assert result.tests == ("//lib:test",)


@pytest.mark.parametrize(
    "roots", [[], ROOTS[:-2], ROOTS + [ROOTS[0]], ROOTS + ["//unknown:test"]]
)
def test_missing_or_invalid_query_roots_are_rejected(roots):
    with pytest.raises(QueryError):
        reconcile_graph(parse_query_xml(GRAPH), roots, native_inventory(reference()))


def test_build_root_must_be_a_rule_not_an_unrelated_source_node():
    value = copy.deepcopy(reference())
    before = next(iter(value["build_target_results"]))
    identifier = json.loads(before)
    identifier["targetCompleted"]["label"] = "//lib:main.cc"
    del value["build_target_results"][before]
    value["build_target_results"][json.dumps(identifier)] = True
    with pytest.raises(QueryError):
        reconcile_graph(
            parse_query_xml(GRAPH), ROOTS + ["//lib:main.cc"], native_inventory(value)
        )


@pytest.fixture
def query_module():
    directory = Path(__file__).resolve().parents[1] / "examples/abseil"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(
            "native_query", directory / "query.py"
        )
        query = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(query)
    finally:
        sys.path.pop(0)
    return query


def test_query_derivation_is_review_bound_and_cannot_execute_native_tests(
    monkeypatch, query_module
):
    query = query_module
    raw = b"""#!/bin/bash
/bin/sh -c "
          /usr/local/bin/bazel test ... \\
            --compilation_mode=fastbuild \\
            ${BAZEL_EXTRA_ARGS:-}"
"""
    with pytest.raises(ValueError):
        query.query_profile(raw)
    monkeypatch.setattr(
        sys.modules["diagnostics"], "PROFILE_SHA256", hashlib.sha256(raw).hexdigest()
    )
    derived = query.query_profile(raw)
    subprocess.run(["bash", "-n"], input=derived, check=True)
    assert b"/bazel test" not in derived
    assert b"--compilation_mode" not in derived
    assert b"set -eu" in derived
    assert b"--noimplicit_deps" not in derived
    assert b"--keep_going" not in derived
    assert b"'deps(//...)'" in derived and b"'buildfiles(deps(//...))'" in derived
    assert derived.count(b"--distdir=/evidence/distdir") == 3
    assert b"--override" not in derived


def test_archive_cache_accepts_only_exact_pinned_bytes(
    tmp_path, monkeypatch, query_module
):
    data = b"verified archive fixture"
    monkeypatch.setattr(query_module, "LIBPFM_SHA256", hashlib.sha256(data).hexdigest())

    def acquire(command, **kwargs):
        assert command[:2] == ["curl", "--disable"]
        assert command[-1] == query_module.LIBPFM_URL
        assert command[command.index("--max-filesize") + 1] == "2097152"
        assert command[command.index("--proto") + 1] == "=https"
        assert command[command.index("--proto-redir") + 1] == "=https"
        assert command[command.index("--max-redirs") + 1] == "4"
        assert kwargs["check"] is True and kwargs["timeout"] == 50
        assert kwargs["env"] == {"PATH": "/usr/bin"}
        Path(command[command.index("--output") + 1]).write_bytes(data)

    monkeypatch.setattr(query_module.subprocess, "run", acquire)
    result = query_module.prepare_archive(tmp_path, {"PATH": "/usr/bin"})
    assert result == {
        "url": query_module.LIBPFM_URL,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    assert (tmp_path / "distdir/libpfm-4.11.0.tar.gz").read_bytes() == data
    assert not (tmp_path / "distdir/libpfm.download").exists()


@pytest.mark.parametrize("defect", ["hash", "size", "timeout", "download", "missing"])
def test_archive_failure_leaves_no_usable_cache(
    tmp_path, monkeypatch, query_module, defect
):
    def acquire(command, **kwargs):
        path = Path(command[command.index("--output") + 1])
        if defect != "missing":
            path.write_bytes(
                b"x" * (query_module.MAX_ARCHIVE_BYTES + 1)
                if defect == "size"
                else b"bad"
            )
        if defect == "timeout":
            raise subprocess.TimeoutExpired(command, 50)
        if defect == "download":
            raise subprocess.CalledProcessError(22, command)

    monkeypatch.setattr(query_module.subprocess, "run", acquire)
    with pytest.raises(QueryError):
        query_module.prepare_archive(tmp_path, {"PATH": "/usr/bin"})
    assert list((tmp_path / "distdir").iterdir()) == []
