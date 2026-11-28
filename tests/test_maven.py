"""Maven reactor safety: native boundaries, conservative fallback and failures."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from smartci import maven


def project(path, dependencies=(), packaging="jar"):
    return maven.Project(
        path,
        "example:" + path,
        frozenset("example:" + d for d in dependencies),
        packaging,
    )


@pytest.fixture
def graph():
    return {
        p.path: p
        for p in [
            project(".", packaging="pom"),
            project("core", ["."]),
            project("rest", ["core"]),
            project("cache", ["core"]),
            project("integration", ["cache"]),
        ]
    }


def test_leaf_selection_keeps_upstream_build_and_global_checks(graph):
    result = maven.select(graph, ["rest/src/main/java/Client.java"])
    assert result["selected_projects"] == [".", "core", "rest"]
    assert result["omitted_projects"] == ["cache", "integration"]
    assert result == maven.select(
        dict(reversed(list(graph.items()))), ["rest/src/main/java/Client.java"]
    )


def test_shared_change_widens_transitively(graph):
    result = maven.select(graph, ["core/src/main/java/Core.java"])
    assert result["mode"] == "full"
    assert result["selected_projects"] == sorted(graph)


def test_changed_test_and_both_rename_owners_are_retained(graph):
    result = maven.select(
        graph, ["rest/src/test/java/Old.java", "cache/src/test/java/New.java"]
    )
    assert result["selected_projects"] == sorted(graph)


@pytest.mark.parametrize(
    "path",
    [
        "pom.xml",
        "rest/pom.xml",
        ".mvn/extensions.xml",
        "rest/src/main/resources/data.json",
        "unowned/src/main/java/File.java",
        "rest/Other.java",
        "README.md",
    ],
)
def test_unknown_global_and_config_changes_run_full(graph, path):
    assert maven.select(graph, [path])["fallback"] == ["GLOBAL_OR_UNSUPPORTED_CHANGE"]


def test_no_change_is_not_permission_to_omit_everything(graph):
    assert maven.select(graph, [])["mode"] == "full"


def model_xml(repo):
    root = ET.Element("projects")
    ns = "{" + maven.NS["m"] + "}"
    for path in (".", "one", "two"):
        node = ET.SubElement(root, ns + "project")
        for name, value in (
            ("groupId", "example"),
            ("artifactId", "parent" if path == "." else path),
            ("packaging", "pom" if path == "." else "jar"),
        ):
            ET.SubElement(node, ns + name).text = value
        if path == ".":
            modules = ET.SubElement(node, ns + "modules")
            for name in ("one", "two"):
                ET.SubElement(modules, ns + "module").text = name
        else:
            deps = ET.SubElement(node, ns + "dependencies")
            dep = ET.SubElement(deps, ns + "dependency")
            ET.SubElement(dep, ns + "groupId").text = "example"
            ET.SubElement(dep, ns + "artifactId").text = "parent"
        build = ET.SubElement(node, ns + "build")
        for name, suffix in (
            ("directory", "target"),
            ("sourceDirectory", "src/main/java"),
            ("testSourceDirectory", "src/test/java"),
        ):
            ET.SubElement(build, ns + name).text = str(repo / path / suffix)
    return ET.tostring(root)


def test_native_models_own_modules_and_aggregate_checks(tmp_path):
    parsed = maven.models(model_xml(tmp_path), tmp_path)
    assert parsed["one"].dependencies == frozenset({"example:parent"})
    assert maven.select(parsed, ["one/src/main/java/X.java"])["selected_projects"] == [
        ".",
        "one",
    ]


@pytest.mark.parametrize(
    "problem",
    [
        "dtd",
        "truncated",
        "oversize",
        "outside",
        "ambiguous",
        "nonstandard",
        "missing",
        "namespace",
        "extension",
    ],
)
def test_invalid_models_cannot_authorize_omissions(tmp_path, problem):
    raw = model_xml(tmp_path)
    if problem == "dtd":
        raw = b'<!DOCTYPE projects [<!ENTITY x "x">]>' + raw
    elif problem == "truncated":
        raw = raw[:100]
    elif problem == "oversize":
        raw = b" " * (maven.MAX_MODEL + 1)
    elif problem == "outside":
        raw = raw.replace(str(tmp_path / "one").encode(), b"/outside")
    elif problem == "ambiguous":
        raw = raw.replace(b">two<", b">one<")
    elif problem == "nonstandard":
        raw = raw.replace(b"src/main/java", b"generated/java")
    elif problem == "missing":
        r = ET.fromstring(raw)
        r.remove(r[-1])
        raw = ET.tostring(r)
    elif problem == "namespace":
        raw = raw.replace(maven.NS["m"].encode(), b"https://invalid")
    elif problem == "extension":
        r = ET.fromstring(raw)
        b = r[0].find("m:build", maven.NS)
        e = ET.SubElement(b, "{" + maven.NS["m"] + "}extensions")
        ET.SubElement(e, "{" + maven.NS["m"] + "}extension")
        raw = ET.tostring(r)
    with pytest.raises((ValueError, ET.ParseError)):
        maven.models(raw, tmp_path)


CONFIG = b"""schema_version = "1"
command = ["./mvnw", "-V", "-Pdocker"]
timeout_seconds = 120
input_contract = "declared-reactor-inputs-v1"
reviewed_native_tree_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
"""


@pytest.mark.parametrize(
    "flag",
    ["-plone", "-pl", "--projects=one", "--resume-from=one", "-am", "-amd", "-N"],
)
def test_already_filtered_full_command_is_rejected(flag):
    with pytest.raises(ValueError):
        maven.configuration(CONFIG.replace(b'"-V"', json.dumps(flag).encode()))


@pytest.mark.parametrize(
    "cause",
    [
        "model-failure",
        "invalid-model",
        "unreviewed",
        "unknown-change",
        "invalid-git",
        "stale-review",
    ],
)
def test_fallback_runs_independent_full_and_preserves_exit(
    tmp_path, monkeypatch, cause
):
    repo = tmp_path / "repo"
    repo.mkdir()
    value = {
        "repo": str(repo),
        "base": "a" * 40,
        "head": "b" * 40,
        "repository": "test/repo",
    }

    def paths(_):
        if cause == "invalid-git":
            raise ValueError("incomplete history")
        return (
            ["pom.xml"] if cause == "unknown-change" else ["one/src/main/java/X.java"]
        )

    monkeypatch.setattr(maven, "changes", paths)
    monkeypatch.setattr(
        maven,
        "native_tree",
        lambda *args: "b" * 64 if cause == "stale-review" else "a" * 64,
    )
    monkeypatch.setattr(maven.control, "verify_head", lambda _: None)
    calls = []

    def invoke(argv, _repo, log, _timeout):
        calls.append(argv)
        if maven.HELP in argv:
            (log.parent / "effective-pom.xml").write_bytes(b"invalid")
            return 1 if cause == "model-failure" else 0
        return 7

    monkeypatch.setattr(maven, "invoke", invoke)
    config = maven.configuration(
        CONFIG.replace(b"declared-reactor-inputs-v1", b"unreviewed")
        if cause == "unreviewed"
        else CONFIG
    )
    output = tmp_path / "out"
    assert maven.run(value, config, output) == 7
    assert calls[-1] == list(config.command)
    assert json.loads((output / "selection.json").read_text())["mode"] == "full"


def test_native_process_excludes_credentials_and_preserves_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    code = "import os; assert 'GH_TOKEN' not in os.environ and 'OPENAI_API_KEY' not in os.environ; print('native evidence'); raise SystemExit(6)"
    assert (
        maven.invoke([sys.executable, "-c", code], tmp_path, tmp_path / "log", 10) == 6
    )
    assert (tmp_path / "log").read_text().strip() == "native evidence"


def test_valid_selection_runs_native_projects_and_preserves_failure(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    value = {
        "repo": str(repo),
        "base": "a" * 40,
        "head": "b" * 40,
        "repository": "test/repo",
    }
    monkeypatch.setattr(maven, "changes", lambda _: ["one/src/test/java/Test.java"])
    monkeypatch.setattr(maven, "native_tree", lambda *args: "a" * 64)
    monkeypatch.setattr(maven.control, "verify_head", lambda _: None)
    calls = []

    def invoke(argv, _repo, log, _timeout):
        calls.append(argv)
        if maven.HELP in argv:
            (log.parent / "effective-pom.xml").write_bytes(model_xml(repo))
            return 0
        return 6

    monkeypatch.setattr(maven, "invoke", invoke)
    assert maven.run(value, maven.configuration(CONFIG), tmp_path / "out") == 6
    assert calls[-1] == ["./mvnw", "-V", "-Pdocker", "--projects", ".,one"]


def test_real_git_rename_and_ignored_inputs(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "old.java").write_text("class Old {}")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("mv", "old.java", "new.java")
    git("commit", "-qm", "rename")
    value = {
        "repo": str(tmp_path),
        "base": base,
        "head": git("rev-parse", "HEAD"),
        "repository": "test/repo",
    }
    assert maven.changes(value) == ["new.java", "old.java"]
    (tmp_path / ".git/info/exclude").write_text("ignored\n")
    (tmp_path / "ignored").write_text("hidden input")
    with pytest.raises(ValueError, match="ignored"):
        maven.changes(value)
