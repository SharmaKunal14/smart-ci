"""Verify change scopes against pinned real Textual PRs; no native tests or models."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.git_changes import git
from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.change_scope import compare
from smartci.investigation.engine import investigate
from smartci.investigation.models import Inputs, Limits
from smartci.investigation.replay import ChangeScopeReplay
from smartci.reports import atomic_write
from smartci.selection import digest

INPUT_SHA256 = "e8188837095af250f14c13f312c226c745e7f64751a4fb922664d1af034a099b"
CASES = {
    "markdown": {
        "pr": "https://github.com/SharmaKunal14/textual/pull/4",
        "base": "e6448b4645e8a7c2935a75abbb748ae017c145a7",
        "head": "6518367d4acda5f92802f6105ede83f7d4ab1543",
        "path": "src/textual/widgets/_markdown.py",
        "source_digests": {
            "base": "1e408bbe56fd450b8ed946fc5943f829ddf70f1fe459c571b79a7525c9f894f8",
            "head": "73092e63a43488a57d1aa66e0996c8340140602d277859d28378b0e9e012a8f6",
        },
        "classification": "function_body_only",
        "changed_callables": [
            "MarkdownFence._copy_context",
            "MarkdownFence._update_from_block",
            "MarkdownTableContent._update_rows",
        ],
    },
    "parser": {
        "pr": "https://github.com/SharmaKunal14/textual/pull/11",
        "base": "ae23055a7898901a3aa69229bf9359b110be739e",
        "head": "b99f72e9691c85f18fd773df427cb5e7a493470d",
        "path": "src/textual/_xterm_parser.py",
        "source_digests": {
            "base": "c5c7512defc06d5d28044c8b021d0209d806f10443c3a04907a86d8cccf26761",
            "head": "fe860b771ae3085ebb4403b3ab6ba903dc4a9b6d825a766a87a4c307c5507b46",
        },
        "classification": "module_or_definition_change",
        "changed_callables": [],
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reports = {}
    for name, case in CASES.items():
        print(f"Checking pinned {name} PR source scope...", flush=True)
        changed = git(
            args.repo,
            "--no-replace-objects",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "-z",
            case["base"],
            case["head"],
        )
        require(
            changed.split(b"\0") == [case["path"].encode(), b""],
            "unexpected PR file scope",
        )
        blobs = {}
        for side in ("base", "head"):
            obj = f"{case[side]}:{case['path']}"
            size = int(git(args.repo, "--no-replace-objects", "cat-file", "-s", obj))
            require(size <= 262_144, "source size exceeds limit")
            raw = git(args.repo, "--no-replace-objects", "cat-file", "blob", obj)
            require(
                hashlib.sha256(raw).hexdigest() == case["source_digests"][side],
                "source identity changed",
            )
            blobs[side] = raw
        report = compare(case["path"], blobs["base"], blobs["head"])
        require(
            report == compare(case["path"], blobs["base"], blobs["head"]),
            "scope changed on replay",
        )
        require(
            report["classification"] == case["classification"],
            "unexpected classification",
        )
        require(
            [row["name"] for row in report["changed_callables"]]
            == case["changed_callables"],
            "unexpected callable scope",
        )
        require(
            report["omission_authorized"] is False
            and report["dependency_completeness_established"] is False,
            "scope must not authorize omissions",
        )
        require(report["callables_truncated"] is False, "incomplete scope output")
        reports[name] = case | {"report": report, "report_digest": digest(report)}

    raw = read_bounded(args.artifact, 32 * 1024 * 1024)
    require(
        hashlib.sha256(raw).hexdigest() == INPUT_SHA256, "PR input artifact changed"
    )
    inputs = Inputs.model_validate_json(raw)
    require(
        inputs.base.commit == CASES["parser"]["base"]
        and inputs.head.commit == CASES["parser"]["head"],
        "PR input revisions mismatch",
    )
    original = inputs.model_dump_json()

    def run():
        return investigate(
            inputs,
            Broker(args.repo, inputs, PythonImports(["src"]), Limits()),
            ChangeScopeReplay(),
            Limits(),
        )

    print(
        "Checking investigator integration, determinism and preserved fallback...",
        flush=True,
    )
    investigation = run()
    require(investigation == run(), "investigation did not replay identically")
    require(inputs.model_dump_json() == original, "input data mutated")
    require(investigation["status"] == "finished", "investigation did not finish")
    require(
        investigation["trace"][0]["kind"] == "compare_source", "comparison tool missing"
    )
    require(
        investigation["trace"][0]["result"]["classification"]
        == "module_or_definition_change",
        "tool result mismatch",
    )
    require(
        investigation["final"]["execution"] == "full"
        and investigation["final"]["fallback"] == ["INCOMPLETE_EVIDENCE"],
        "full fallback was not preserved",
    )
    require(
        investigation["unresolved"] == sorted(inputs.unresolved), "unknowns changed"
    )
    require(
        not investigation["accepted_graph"]["evidence"],
        "scope was promoted to edge evidence",
    )
    for side in ("base", "head"):
        require(
            investigation["accepted_graph"][side] == getattr(inputs, side).model_dump(),
            "graph changed",
        )
    require(investigation["model_calls"] == 0, "unexpected model accounting")
    atomic_write(
        args.output / "investigation.json", json.dumps(investigation, sort_keys=True)
    )
    result = {
        "schema_version": "smartci.change-scope-audit.v1",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "workflow_sha": os.environ.get("GITHUB_SHA"),
        "cases": reports,
        "deterministic_replay": True,
        "source_input_sha256": INPUT_SHA256,
        "investigation_digest": investigation["digest"],
        "selected_test_files": len(investigation["final"]["selected"]),
        "unresolved_preserved": len(inputs.unresolved),
        "execution_required": "full",
        "test_execution": "none; source-only investigation audit",
        "model_calls": 0,
        "speedup_demonstrated": False,
        "model_effectiveness_measured": False,
    }
    atomic_write(args.output / "summary.json", json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "classifications": {
                    name: row["report"]["classification"]
                    for name, row in reports.items()
                },
                "execution_required": "full",
                "model_calls": 0,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
