"""One live investigator; experiment-only additions never override production fallback."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from benchmark import revision, write
from compare_observation import read
from runtime_candidate import REPOSITORY, enrollment

from smartci.contracts import Inventory, TestUnit
from smartci.git_changes import changes_from_git, git
from smartci.investigation.adapters import PythonImports
from smartci.investigation.broker import Broker
from smartci.investigation.budget import Ledger
from smartci.investigation.engine import investigate
from smartci.investigation.github_budget import GitHubBudget
from smartci.investigation.http import HTTPS
from smartci.investigation.models import Accepted, Inputs, Inspect, Limits, Propose
from smartci.investigation.openai_provider import OpenAIProvider
from smartci.investigation.process_scripts import PythonProcessScripts
from smartci.investigation.public_scope import validate_public_scope
from smartci.investigation.runtime_scope import ObservedRun, candidate, tree
from smartci.selection import Graph, SelectionPolicy, digest


def inputs_from_observation(root, base, head, observed, environment):
    """Persist positive base observations; never pretend they were observed at head."""
    paths = sorted(p for p in tree(root, base) if p.endswith(".py"))
    if len(paths) > 10_000 or paths != sorted(
        p for p in tree(root, head) if p.endswith(".py")
    ):
        raise ValueError("stable bounded Python source inventory required")
    owners = {p: "file:" + digest(p) for p in paths}
    if not set(observed.test_files) <= owners.keys():
        raise ValueError("observed inventory outside source catalog")
    catalogs, blobs, total = {}, {}, 0
    for commit in (base, head):
        catalog = {}
        for path, blob in tree(root, commit).items():
            if path not in owners:
                continue
            if blob not in blobs:
                if (
                    int(git(root, "--no-replace-objects", "cat-file", "-s", blob))
                    > 262_144
                ):
                    raise ValueError("source exceeds inspector limit")
                raw = git(root, "--no-replace-objects", "cat-file", "blob", blob)
                total += len(raw)
                if total > 16 * 1024 * 1024:
                    raise ValueError("source catalog exceeds limit")
                blobs[blob] = hashlib.sha256(raw).hexdigest()
            catalog[path] = blobs[blob]
        catalogs[commit] = catalog
    dependencies = {node: set() for node in owners.values()}
    tests = set(observed.test_files)
    for context, values in observed.contexts.items():
        metadata = observed.context_metadata.get(context)
        if context in tests:
            callers = {context}
        elif (
            metadata
            and metadata.scope in {"function", "class", "module"}
            and metadata.owner in tests
        ):
            callers = {metadata.owner}
        elif metadata and metadata.scope == "package" and metadata.owner != ".":
            callers = {t for t in tests if t.startswith(metadata.owner + "/")} or tests
        else:
            callers = tests
        targets = {owners[p] for p in values.code_files if p in owners}
        for caller in callers:
            dependencies[owners[caller]].update(targets)
    common = {
        "schema_version": "1",
        "repository": REPOSITORY,
        "complete": False,
        "owners": owners,
        "tests": {t: owners[t] for t in tests},
    }
    return Inputs(
        changes=changes_from_git(root, base, head, REPOSITORY),
        inventory=Inventory(
            schema_version="1",
            repository=REPOSITORY,
            complete=False,
            environment=digest(environment),
            tests=[
                TestUnit(id=t, path=t, runner="pytest", granularity="file")
                for t in sorted(tests)
            ],
        ),
        base=Graph(
            **common,
            commit=base,
            dependencies={n: sorted(d) for n, d in dependencies.items()},
        ),
        head=Graph(
            **common, commit=head, dependencies={n: [] for n in owners.values()}
        ),
        sources=catalogs,
        policy=SelectionPolicy(
            schema_version="1",
            repository=REPOSITORY,
            mode="selective",
            allow_source_excerpts=True,
        ),
        unresolved=sorted(
            set(
                observed.limitations
                + observed.diagnostics
                + ["HEAD_RUNTIME_NOT_OBSERVED", "SHADOW_ONLY_NO_OMISSION_AUTHORITY"]
            )
        ),
    )


def expand(root, initial, inputs, report):
    """Use verified incoming relationships to add tests; never remove the initial set."""
    if report["input_digest"] != inputs.identity():
        raise ValueError("investigation input mismatch")
    if report["digest"] != digest({k: v for k, v in report.items() if k != "digest"}):
        raise ValueError("investigation integrity mismatch")
    if report["final"]["execution"] != "full":
        raise ValueError("production fallback changed")
    selected = set(initial["candidate_files"])
    added = set()
    if report["status"] != "finished":
        selected = set(initial["inventory_files"])
    else:
        graphs = (inputs.base, inputs.head)
        reverse = {n: set() for graph in graphs for n in graph.dependencies}
        for graph in graphs:
            for source, targets in graph.dependencies.items():
                for target in targets:
                    reverse[target].add(source)
        edges = [
            Accepted.model_validate(e) for e in report["accepted_graph"]["evidence"]
        ]
        if len(edges) > 4:
            raise ValueError("investigation exceeds evidence bound")
        verifier = Broker(
            root,
            inputs,
            PythonImports(["src"]),
            Limits(),
            additional_adapters=(PythonProcessScripts(),),
        )
        for edge in edges:
            verifier.inspect(
                Inspect(
                    kind="inspect",
                    revision=edge.revision,
                    path=edge.path,
                    adapter=edge.verifier,
                )
            )
            claim = Propose.model_validate(
                edge.model_dump(include=set(Propose.model_fields))
            )
            if verifier.verify(claim) != edge:
                raise ValueError("accepted evidence failed independent replay")
        for edge in edges:
            graph = inputs.base if edge.revision == inputs.base.commit else inputs.head
            reverse[graph.owners[edge.target]].add(graph.owners[edge.path])

        def ancestors(seeds):
            visited = set(seeds)
            pending = list(seeds)
            while pending:
                node = pending.pop()
                for parent in reverse[node] - visited:
                    visited.add(parent)
                    pending.append(parent)
            return visited

        impact = ancestors(
            {
                graph.owners[p]
                for graph in graphs
                for p in inputs.changes.paths
                if p in graph.owners
            }
        )
        for edge in edges:
            if edge.already_recorded:
                continue
            graph = inputs.base if edge.revision == inputs.base.commit else inputs.head
            if graph.owners[edge.target] in impact:
                callers = ancestors({graph.owners[edge.path]})
                added.update(t for t, node in graph.tests.items() if node in callers)
        selected.update(added)
    result = {k: v for k, v in initial.items() if k != "digest"}
    result.update(
        candidate_files=sorted(selected),
        initial_candidate_digest=initial["digest"],
        investigation_digest=report["digest"],
        agent_added_files=sorted(added - set(initial["candidate_files"])),
        model_calls=report["model_calls"],
        agent_status=report["status"],
    )
    if report["status"] != "finished":
        result["fallback"] = sorted(set(result["fallback"]) | {"AGENT_INCOMPLETE"})
    return result | {"digest": digest(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=revision, required=True)
    parser.add_argument("--head", type=revision, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = Path.cwd(), args.output.resolve()
    started = time.monotonic()
    environment = json.loads(read(output / "profile.json"))
    enrollment(args.enrollment, args.base, environment)
    raw = read(args.enrollment / "textual-observe-scoped-1/observation.json")
    initial = candidate(root, args.base, args.head, raw)
    if initial["fallback"]:
        raise ValueError("eligible deterministic candidate required")
    observed = ObservedRun.model_validate_json(raw)
    inputs = inputs_from_observation(root, args.base, args.head, observed, environment)
    write(output / "agent-input.json", inputs.model_dump())
    prepared = time.monotonic()
    if os.environ.get("SMARTCI_DISABLE_MODEL_CALLS") != "0":
        raise ValueError("live invocation not explicitly enabled")
    github = HTTPS("api.github.com", os.environ.get("GITHUB_TOKEN", ""))
    validate_public_scope(inputs, github)
    ledger = Ledger(
        GitHubBudget(
            github,
            "SharmaKunal14/smart-ci",
            "codex/model-budget-textual-public-20261123",
        ),
        "textual-public-20261123",
    )
    provider = OpenAIProvider(
        HTTPS("api.openai.com", os.environ.get("OPENAI_API_KEY", "")),
        ledger,
        digest({"input": inputs.identity(), "trial": 2}),
        initial_context={
            "task": "Find positive incoming dependencies missing from the advisory runtime map. Source inspection may establish additional tests; never remove known dependencies or infer independence from absence.",
            "candidate_digest": initial["digest"],
            "candidate_files": initial["candidate_files"][:20],
            "candidate_count": len(initial["candidate_files"]),
            "unobserved_changed_callables": initial["unobserved_changed_callables"],
            "scope": "shadow experiment with mandatory independent full control",
        },
    )
    limits = Limits(steps=4, seconds=120)
    report = investigate(
        inputs,
        Broker(
            root,
            inputs,
            PythonImports(["src"]),
            limits,
            additional_adapters=(PythonProcessScripts(),),
        ),
        provider,
        limits,
    )
    final = expand(root, initial, inputs, report)
    if final != expand(root, initial, inputs, report):
        raise ValueError("non-deterministic evidence application")
    write(output / "initial-candidate.json", initial)
    write(output / "agent.json", report)
    write(output / "candidate.json", final)
    write(
        output / "targets.json",
        None
        if final["candidate_files"] == final["inventory_files"]
        else final["candidate_files"],
    )
    write(
        output / "agent-timing.json",
        {
            "preparation_and_model_seconds": time.monotonic() - started,
            "source_preparation_seconds": prepared - started,
            "model_and_tool_seconds": time.monotonic() - prepared,
        },
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "model_calls": report["model_calls"],
                "added_files": final["agent_added_files"],
            }
        ),
        flush=True,
    )
    return 0 if report["status"] == "finished" else 2


if __name__ == "__main__":
    raise SystemExit(main())
