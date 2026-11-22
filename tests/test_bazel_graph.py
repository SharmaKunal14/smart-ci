import pytest

from smartci.bazel.graph import QueryError, parse_query_xml

GRAPH = b"""<query version="2">
<source-file name="//schema:event.proto"/>
<source-file name="//other:other.cc"/>
<rule class="genrule" name="//schema:generate"><rule-input name="//schema:event.proto"/></rule>
<generated-file name="//schema:event.h" generating-rule="//schema:generate"/>
<rule class="cc_library" name="//lib:core"><rule-input name="//schema:event.h"/></rule>
<rule class="cc_test" name="//lib:test"><rule-input name="//lib:core"/><list name="tags"><string value="small"/></list></rule>
<rule class="cc_binary" name="//cli:application"><rule-input name="//lib:core"/></rule>
<rule class="cc_test" name="//other:test"><rule-input name="//other:other.cc"/></rule>
</query>"""


def test_generated_sources_and_non_test_build_targets_are_preserved():
    graph = parse_query_xml(GRAPH)
    affected = graph.affected(["schema/event.proto"])
    assert set(affected) == {
        "//schema:generate",
        "//lib:core",
        "//lib:test",
        "//cli:application",
    }
    assert affected["//lib:test"] == [
        "//lib:test",
        "//lib:core",
        "//schema:event.h",
        "//schema:generate",
        "//schema:event.proto",
    ]
    assert graph.rule_tags["//lib:test"] == ("small",)


def test_query_order_and_change_order_do_not_change_impact():
    rows = GRAPH.decode().splitlines()
    reversed_graph = (
        rows[0] + "\n" + "\n".join(reversed(rows[1:-1])) + "\n" + rows[-1]
    ).encode()
    first = parse_query_xml(GRAPH)
    second = parse_query_xml(reversed_graph)
    assert first == second
    assert first.affected(["schema/event.proto", "other/other.cc"]) == second.affected(
        ["other/other.cc", "schema/event.proto"]
    )


def test_implicit_external_and_all_declared_branch_inputs_are_kept():
    raw = b"""<query>
    <source-file name="//pkg:linux.cc"/><source-file name="//pkg:windows.cc"/>
    <source-file name="@@tools+//:compiler"/>
    <rule class="cc_test" name="//pkg:test"><rule-input name="//pkg:linux.cc"/><rule-input name="//pkg:windows.cc"/><rule-input name="@@tools+//:compiler"/></rule>
    </query>"""
    graph = parse_query_xml(raw)
    assert "@@tools+//:compiler" in graph.dependencies["//pkg:test"]
    assert graph.affected(["pkg/windows.cc"])["//pkg:test"][-1] == "//pkg:windows.cc"
    assert "compiler" not in graph.source_owners


@pytest.mark.parametrize(
    "raw",
    [
        b'<query><rule name="//a:b" class="cc_test"><rule-input name="//missing:input"/></rule></query>',
        b'<query><source-file name="//a:../escape"/></query>',
        b'<query><source-file name="//a:b"/><source-file name="//a:b"/></query>',
        b'<query><generated-file name="//a:b"/></query>',
        b'<!DOCTYPE query [<!ENTITY x "bad">]><query/>',
        '<!DOCTYPE query [<!ENTITY x "bad">]><query/>'.encode("utf-16"),
        b'<query><unknown name="//a:b"/></query>',
        b"<query/>",
        b"<not-query/>",
        GRAPH[:-5],
    ],
)
def test_invalid_or_partial_evidence_is_rejected(raw):
    with pytest.raises(QueryError):
        parse_query_xml(raw)


def test_unknown_changes_do_not_mean_no_impact():
    graph = parse_query_xml(GRAPH)
    for paths in [[], ["unknown/file.cc"], ["schema/event.proto", "unknown/file.cc"]]:
        with pytest.raises(QueryError):
            graph.affected(paths)


def test_cycles_terminate_with_a_dependency_witness():
    graph = parse_query_xml(b"""<query><source-file name="//:input.cc"/>
    <rule class="alias" name="//:a"><rule-input name="//:b"/><rule-input name="//:input.cc"/></rule>
    <rule class="alias" name="//:b"><rule-input name="//:a"/></rule></query>""")
    assert graph.affected(["input.cc"])["//:b"] == ["//:b", "//:a", "//:input.cc"]


def test_excessive_dependency_depth_requires_fallback(monkeypatch):
    monkeypatch.setattr("smartci.bazel.graph.MAX_WITNESS_DEPTH", 2)
    with pytest.raises(QueryError, match="bounded"):
        parse_query_xml(GRAPH).affected(["schema/event.proto"])
