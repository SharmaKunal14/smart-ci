import copy

import pytest

from smartci.bazel.audit import NativeInventory
from smartci.bazel.graph import QueryError, parse_query_xml
from smartci.bazel.planning import TreeEntry, candidate_plan, parse_tree

GRAPH = b"""<query>
<source-file name="//lib:one.h"/><source-file name="//lib:two.cc"/>
<rule name="//lib:one" class="cc_library"><rule-input name="//lib:one.h"/></rule>
<rule name="//lib:one_test" class="cc_test"><rule-input name="//lib:one"/></rule>
<rule name="//lib:two_test" class="cc_test"><rule-input name="//lib:two.cc"/></rule>
<rule name="//lib:binary" class="cc_binary"><rule-input name="//lib:one"/></rule>
</query>"""
GRAPH_VALUE = parse_query_xml(GRAPH)
ROOTS = list(GRAPH_VALUE.rule_classes)
NATIVE = NativeInventory(
    {n: ("a" * 64,) for n in ROOTS}, ("//lib:one_test", "//lib:two_test")
)
ANCHOR = {
    p: TreeEntry("100644", "a" * 40)
    for p in [
        "lib/one.h",
        "lib/two.cc",
        "lib/BUILD",
        "MODULE.bazel",
        "data/config.json",
    ]
}


def modified(path="lib/one.h"):
    tree = dict(ANCHOR)
    tree[path] = TreeEntry("100644", "b" * 40)
    return tree


def plan(head, base=None, **kwargs):
    return candidate_plan(
        ANCHOR,
        ANCHOR if base is None else base,
        head,
        GRAPH_VALUE,
        ROOTS,
        NATIVE,
        **kwargs,
    )


def test_existing_declared_source_change_preserves_native_build_only_roots():
    result = plan(modified())
    assert result["mode"] == "subset"
    assert result["selected"] == ["//lib:one_test"]
    assert result["patterns"] == ["...", "-//lib:two_test"]
    assert result["build_only"] == ["//lib:binary", "//lib:one"]
    assert result["witnesses"]["//lib:one_test"] == [
        "//lib:one_test",
        "//lib:one",
        "//lib:one.h",
    ]
    assert result["production_omission_authorized"] is False
    assert result["requires_independent_full_control"] is True


def test_anchor_can_precompute_unchanged_topology_for_both_revisions():
    base = modified("lib/two.cc")
    head = dict(base)
    head["lib/one.h"] = TreeEntry("100644", "c" * 40)
    result = plan(head, base)
    assert result["selected"] == ["//lib:one_test"]
    # Prior source changes are harmless to declared topology; only this PR's
    # changed file determines impact. Build definitions must match the anchor.
    base["lib/BUILD"] = TreeEntry("100644", "c" * 40)
    assert "MAP_INPUTS_CHANGED" in plan(head, base)["fallback"]


def test_reverting_source_to_anchor_still_selects_its_tests():
    assert plan(ANCHOR, modified())["selected"] == ["//lib:one_test"]


@pytest.mark.parametrize(
    "kind",
    [
        "build",
        "resource",
        "dependency",
        "added",
        "deleted",
        "renamed",
        "mode",
        "symlink",
        "unknown",
        "workflow",
        "harness",
    ],
)
def test_unsupported_or_topology_changes_fall_back_to_full(kind):
    head = modified()
    if kind in {"build", "resource", "dependency", "unknown", "workflow", "harness"}:
        path = {
            "build": "lib/BUILD",
            "resource": "data/config.json",
            "dependency": "MODULE.bazel",
            "unknown": "lib/new.h",
            "workflow": ".github/workflows/pilot.yml",
            "harness": ".smartci/run.py",
        }[kind]
        head[path] = TreeEntry("100644", "c" * 40)
    elif kind in {"deleted", "renamed"}:
        del head["lib/two.cc"]
        if kind == "renamed":
            head["lib/moved.cc"] = ANCHOR["lib/two.cc"]
    elif kind == "added":
        head["lib/added.cc"] = TreeEntry("100644", "c" * 40)
    else:
        head["lib/one.h"] = TreeEntry(
            "120000" if kind == "symlink" else "100755", "c" * 40
        )
    result = plan(head)
    assert result["mode"] == "full" and result["fallback"]
    assert result["patterns"] == ["..."]
    assert result["selected"] == list(NATIVE.tests)


def test_reviewed_setup_files_may_differ_from_anchor_but_not_within_pr():
    base = dict(ANCHOR)
    base[".github/workflows/pilot.yml"] = TreeEntry("100644", "c" * 40)
    head = dict(base)
    head["lib/one.h"] = TreeEntry("100644", "d" * 40)
    assert plan(head, base)["mode"] == "subset"
    head[".github/workflows/pilot.yml"] = TreeEntry("100644", "e" * 40)
    assert plan(head, base)["mode"] == "full"


def test_must_run_adds_tests_and_unknown_policy_falls_back():
    result = plan(modified(), must_run=("//lib:two_test",))
    assert result["selected"] == list(NATIVE.tests)
    assert result["mode"] == "full" and result["fallback"] == []
    assert plan(modified(), must_run=("//unknown:test",))["fallback"] == [
        "INVALID_MUST_RUN"
    ]


def test_empty_change_or_impact_cannot_silently_omit_all_tests():
    assert plan(ANCHOR)["fallback"] == ["NO_CODE_CHANGE"]
    graph = copy.deepcopy(GRAPH_VALUE)
    graph.dependencies["//lib:one_test"] = ()
    result = candidate_plan(ANCHOR, ANCHOR, modified(), graph, ROOTS, NATIVE)
    assert result["fallback"] == ["NO_IMPACT_EVIDENCE"]


def test_map_missing_a_native_root_is_not_usable():
    with pytest.raises(QueryError):
        candidate_plan(ANCHOR, ANCHOR, modified(), GRAPH_VALUE, ROOTS[:-1], NATIVE)


def test_plan_and_digest_are_deterministic_under_input_reordering():
    result = plan(modified())
    reordered = candidate_plan(
        dict(reversed(list(ANCHOR.items()))),
        ANCHOR,
        dict(reversed(list(modified().items()))),
        GRAPH_VALUE,
        list(reversed(ROOTS)),
        NATIVE,
    )
    assert result == reordered


def test_excessive_exclusion_lists_fall_back_before_execution():
    graph = copy.deepcopy(GRAPH_VALUE)
    configurations = dict(NATIVE.build_configurations)
    tests = list(NATIVE.tests)
    for i in range(1001):
        name = f"//many:test_{i}"
        graph.dependencies[name] = ()
        graph.rule_classes[name] = "cc_test"
        graph.rule_tags[name] = ()
        configurations[name] = ("a" * 64,)
        tests.append(name)
    result = candidate_plan(
        ANCHOR,
        ANCHOR,
        modified(),
        graph,
        list(graph.rule_classes),
        NativeInventory(configurations, tuple(sorted(tests))),
    )
    assert result["mode"] == "full"
    assert result["patterns"] == ["..."]
    assert result["fallback"] == ["TARGET_PATTERN_EVIDENCE_LIMIT"]


def test_tree_parser_retains_modes_and_blob_identity():
    raw = b"100644 blob " + b"a" * 40 + b"\tlib/one.h\0"
    assert parse_tree(raw) == {"lib/one.h": TreeEntry("100644", "a" * 40)}
    for invalid in [
        b"",
        raw[:-1],
        raw + raw,
        raw.replace(b"lib/one.h", b"../escape"),
        raw.replace(b"blob", b"tree"),
        raw.replace(b"100644", b"123456"),
    ]:
        with pytest.raises(QueryError):
            parse_tree(invalid)
