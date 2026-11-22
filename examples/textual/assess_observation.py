"""Explain positive observations. This is deliberately not a selection adapter."""

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path


def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("report exceeds analysis limit")
    return json.loads(raw)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, timeout=15
    ).stdout


def enclosing_entry(source, line):
    functions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line <= node.end_lineno
    ]
    if not functions:
        return None
    node = min(functions, key=lambda node: node.end_lineno - node.lineno)
    first = min([node.lineno, *[d.lineno for d in node.decorator_list]])
    return {"name": node.name, "line": first}


def assess(root, report, compatibility, changed_paths):
    if (
        report["schema"]
        not in {"smartci.runtime-observation.v1", "smartci.runtime-observation.v2"}
        or report["complete"] is not False
        or report["omission_authorized"] is not False
        or not re.fullmatch(r"[a-f0-9]{40}", report["commit"])
        or not re.fullmatch(r"[a-f0-9]{40}", compatibility["commit"])
    ):
        raise ValueError("unsupported or invalid observation")
    unsigned = {key: value for key, value in report.items() if key != "digest"}
    if (
        hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != report["digest"]
    ):
        raise ValueError("observation digest mismatch")
    tests = set(report["test_files"])

    def scope_files(context):
        if context in tests:
            return {context}
        metadata = report.get("context_metadata", {}).get(context, {})
        if report["schema"] != "smartci.runtime-observation.v2" or metadata.get(
            "kind"
        ) not in {"collection", "fixture_setup"}:
            return tests
        scope = metadata.get("scope")
        owner = metadata.get("owner")
        if scope in {"function", "class", "module"} and owner in tests:
            return {owner}
        if (
            scope == "package"
            and isinstance(owner, str)
            and owner in {str(Path(t).parent) for t in tests}
        ):
            return {t for t in tests if t.startswith(owner + "/")}
        return tests

    def contexts(path, entry=None):
        found = []
        for context, values in report["contexts"].items():
            hit = (
                f"{path}:{entry}" in values.get("code_entries", [])
                if entry is not None
                else path
                in set(values.get("code_files", []))
                | set(values.get("open_attempts", []))
            )
            if hit:
                found.append(context)
        return sorted(found)

    gaps = []
    for gap in compatibility["gaps"]:
        path = gap["path"]
        row = {**gap, "resolved": False, "function": None, "observed_contexts": []}
        if path in report["tracked_blobs"]:
            old_source = git(root, "show", f"{compatibility['commit']}:{path}")
            source = git(root, "show", f"{report['commit']}:{path}")
            blob = git(root, "rev-parse", f"{report['commit']}:{path}").decode().strip()
            if source != old_source or blob != report["tracked_blobs"][path]:
                raise ValueError("gap source revision differs from observation")
            function = enclosing_entry(source, gap["line"])
            row["function"] = function
            row["observed_contexts"] = contexts(
                path, function["line"] if function else None
            )
        gaps.append(row)

    candidates = []
    for path in changed_paths:
        if path not in report["tracked_blobs"]:
            raise ValueError("candidate path must be tracked in observed revision")
        observed = set(contexts(path))
        calls = sorted(observed & tests)
        shared = sorted(observed - tests)
        scoped = set().union(*(scope_files(context) for context in observed))
        candidates.append(
            {
                "path": path,
                "observed_call_files": calls,
                "shared_contexts": shared,
                "candidate_files_including_shared": sorted(scoped),
                "omission_authorized": False,
            }
        )
    return {
        "schema": "smartci.runtime-assessment.v2",
        "commit": report["commit"],
        "observation_digest": report["digest"],
        "native_case_count": report["case_count"],
        "test_file_count": len(tests),
        "gaps": gaps,
        "candidates": candidates,
        "execution_required": "full",
        "omission_authorized": False,
        "reason": "positive runtime observations do not establish graph completeness",
        "interpretation": "temporal scope is not exclusive dependency ownership; function entry is not branch coverage",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--compatibility", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assess(
        args.repo, read_json(args.observation), read_json(args.compatibility), args.path
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
