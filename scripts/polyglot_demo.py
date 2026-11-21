"""Real local regression demonstrations in a disposable Git repository."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from smartci.adapters.suite import Discovered, discover, execute
from smartci.git_changes import changes_from_git
from smartci.reports import atomic_write, markdown
from smartci.selection import Graph, SelectionPolicy, select

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "examples/polyglot"
OUTPUT = PROJECT / "demo-output/polyglot"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(root),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


def graph(suite: Discovered, commit: str) -> Graph:
    # Explicit reviewed fixture graph, not inferred cross-language dependencies.
    owners = {
        "python/auth.py": "auth",
        "python/test_auth.py": "auth",
        "python/conftest.py": "auth",
        "ts/checkout.ts": "checkout",
        "ts/checkout.test.ts": "checkout",
        "java/src/main/java/demo/Pricing.java": "pricing",
        "java/src/test/java/demo/PricingTest.java": "pricing",
    }
    return Graph(
        schema_version="1",
        repository=suite.config.repository,
        commit=commit,
        complete=True,
        owners=owners,
        dependencies={"auth": [], "checkout": ["auth"], "pricing": []},
        tests={u.id: entry.name for entry, _, units in suite.runners for u in units},
    )


def save(name: str, value: object) -> None:
    atomic_write(OUTPUT / name, json.dumps(value, indent=2) + "\n")


def main() -> None:
    if not (SOURCE / "ts/node_modules/vitest/vitest.mjs").is_file():
        raise RuntimeError("Run make polyglot-setup first")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smartci-polyglot-") as directory:
        root = Path(directory) / "repo"
        shutil.copytree(
            SOURCE,
            root,
            ignore=shutil.ignore_patterns(
                "node_modules", "target", "__pycache__", ".pytest_cache"
            ),
        )
        # Reuse installed, pinned tools. Only temporary source files are mutated.
        (root / "ts/node_modules").symlink_to(
            SOURCE / "ts/node_modules", target_is_directory=True
        )
        (root / ".gitignore").write_text(
            "node_modules\ntarget/\n__pycache__/\n.pytest_cache/\n"
        )
        git(root, "init", "-q")
        git(root, "config", "user.name", "Smart CI fixture")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline")
        base = git(root, "rev-parse", "HEAD")
        baseline = discover(root / "smartci.json")
        result = execute(baseline)
        save("baseline.execution.json", result)
        if result["status"] != "passed":
            raise RuntimeError(
                "Baseline full suite did not pass; inspect baseline.execution.json"
            )
        print("baseline: full; auth, checkout, pricing passed", flush=True)
        scenarios = [
            (
                "pricing-defect",
                "java/src/main/java/demo/Pricing.java",
                "* 100",
                "* 101",
                "selective",
                "subset",
                "failed",
                {"pricing"},
            ),
            (
                "auth-defect",
                "python/auth.py",
                '"role": role',
                '"permission": role',
                "selective",
                "subset",
                "failed",
                {"auth", "checkout"},
            ),
            (
                "shadow-auth",
                "python/auth.py",
                "import json",
                "import json\n# harmless change",
                "shadow",
                "subset",
                "passed",
                {"auth", "checkout", "pricing"},
            ),
            (
                "lockfile",
                "ts/package-lock.json",
                None,
                "\n",
                "selective",
                "full",
                "passed",
                {"auth", "checkout", "pricing"},
            ),
            (
                "migration",
                "migrations/001.sql",
                None,
                "-- sample schema change\n",
                "selective",
                "full",
                "passed",
                {"auth", "checkout", "pricing"},
            ),
            (
                "shared-setup",
                "python/conftest.py",
                None,
                "\n# shared fixture change\n",
                "selective",
                "full",
                "passed",
                {"auth", "checkout", "pricing"},
            ),
        ]
        for (
            name,
            filename,
            old,
            new,
            policy_mode,
            proposed,
            expected,
            executed,
        ) in scenarios:
            git(root, "reset", "--hard", base)
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            source = path.read_text() if path.exists() else ""
            if old is not None and old not in source:
                raise RuntimeError("Defect injection did not match source")
            path.write_text(
                source.replace(old, new) if old is not None else source + new
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", name)
            head = git(root, "rev-parse", "HEAD")
            suite = discover(root / "smartci.json")
            changes = changes_from_git(root, base, head, suite.config.repository)
            policy = SelectionPolicy.model_validate(
                {
                    "schema_version": "1",
                    "repository": suite.config.repository,
                    "mode": policy_mode,
                    "full_paths": ["smartci.json", "**/pytest.ini"],
                }
            )
            base_graph, head_graph = graph(baseline, base), graph(suite, head)
            decision = select(changes, suite.inventory, base_graph, head_graph, policy)
            for suffix, data in (
                ("inventory", suite.inventory),
                ("changes", changes),
                ("base-graph", base_graph),
                ("head-graph", head_graph),
                ("policy", policy),
                ("selection", decision),
            ):
                save(f"{name}.{suffix}.json", data.model_dump())
            atomic_write(OUTPUT / f"{name}.audit.md", markdown(decision))
            result = execute(suite, decision)
            save(f"{name}.execution.json", result)
            actual_suites = {attempt["suite"] for attempt in result["attempts"]}
            if (
                decision.mode != proposed
                or result["status"] != expected
                or actual_suites != executed
            ):
                raise RuntimeError(
                    f"Unexpected scenario outcome: {name}; inspect saved artifacts"
                )
            if name == "auth-defect":
                outcomes = {a["suite"]: a["status"] for a in result["attempts"]}
                if outcomes != {"auth": "passed", "checkout": "failed"}:
                    raise RuntimeError("Cross-language regression was not demonstrated")
            print(
                f"{name}: proposed={decision.mode}; execution={result['execution']}; {result['status']} (expected); suites={','.join(sorted(actual_suites))}; fallback={decision.fallback}",
                flush=True,
            )
    print(f"All six scenarios verified. Artifacts: {OUTPUT}")


if __name__ == "__main__":
    main()
