"""Package trusted native captures and plan from authenticated evidence bundles."""

import argparse
import json
import re
from pathlib import Path

from smartci.git_changes import git
from smartci.reports import atomic_write

from .bundle import (
    LIMITS,
    MAX_MANIFEST_BYTES,
    canonical,
    load,
    pack,
    parse_profile,
    read_bounded,
    sha256,
)
from .collection import collect, read_config
from .graph import QueryError
from .planning import MAX_TREE_BYTES, parse_tree

GIT_OPTIONS = ("--no-replace-objects", "-c", "core.fsmonitor=false")


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parent = sub.add_parser(
        "bazel", help="validated native Bazel evidence and planning"
    )
    commands = parent.add_subparsers(dest="bazel_command", required=True)
    collection = commands.add_parser(
        "collect", help="collect or safely reuse native evidence from trusted commands"
    )
    collection.add_argument("--repo", type=Path, required=True)
    collection.add_argument("--revision", required=True)
    collection.add_argument("--config", type=Path, required=True)
    collection.add_argument("--output", type=Path, required=True)
    collection.add_argument("--reuse-bundle", type=Path)
    collection.add_argument("--expected-digest")
    packaging = commands.add_parser(
        "pack",
        help="package a trusted full native capture; does not collect or run tests",
    )
    packaging.add_argument("--repo", type=Path, required=True)
    packaging.add_argument("--revision", required=True)
    packaging.add_argument("--profile", type=Path, required=True)
    packaging.add_argument("--query", type=Path, required=True)
    packaging.add_argument("--roots", type=Path, required=True)
    packaging.add_argument("--native-bep", type=Path, required=True)
    packaging.add_argument("--output", type=Path, required=True)
    planning = commands.add_parser(
        "plan", help="produce a deterministic plan; never run tests"
    )
    planning.add_argument("--repo", type=Path, required=True)
    planning.add_argument("--base", required=True)
    planning.add_argument("--head", required=True)
    planning.add_argument("--profile", type=Path, required=True)
    planning.add_argument("--bundle", type=Path, required=True)
    planning.add_argument("--expected-digest", required=True)
    planning.add_argument("--must-run", action="append", default=[])
    planning.add_argument(
        "--execution-mode", choices=["paired", "selective"], default="paired"
    )
    planning.add_argument("--output", type=Path, required=True)


def revision_tree(repo: Path, revision: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise QueryError("exact commit required")
    if git(repo, *GIT_OPTIONS, "cat-file", "-t", revision).strip() != b"commit":
        raise QueryError("commit object required")
    return git(
        repo,
        *GIT_OPTIONS,
        "ls-tree",
        "-rz",
        "--full-tree",
        revision,
        max_bytes=MAX_TREE_BYTES,
    )


def verify_checkout(repo: Path, revision: str) -> bytes:
    tree = revision_tree(repo, revision)
    if (
        Path(
            git(repo, *GIT_OPTIONS, "rev-parse", "--show-toplevel").decode().strip()
        ).resolve()
        != repo
    ):
        raise QueryError("repository root required")
    if git(repo, *GIT_OPTIONS, "rev-parse", "HEAD").decode().strip() != revision:
        raise QueryError("checkout revision mismatch")
    git(
        repo,
        *GIT_OPTIONS,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--exit-code",
        revision,
        "--",
    )
    if git(repo, *GIT_OPTIONS, "ls-files", "--others", "-z"):
        raise QueryError("untracked or ignored capture inputs")
    return tree


def pack_command(args: argparse.Namespace) -> int:
    try:
        repo, output = args.repo.resolve(), args.output.resolve()
        if output.is_relative_to(repo):
            raise QueryError("evidence output must be outside repository")
        tree = verify_checkout(repo, args.revision)
        profile = parse_profile(read_bounded(args.profile, MAX_MANIFEST_BYTES))
        artifacts = {
            "anchor.tree": tree,
            "query.xml": read_bounded(args.query, LIMITS["query.xml"]),
            "roots.txt": read_bounded(args.roots, LIMITS["roots.txt"]),
            "native.bep.json": read_bounded(args.native_bep, LIMITS["native.bep.json"]),
        }
        bundle = pack(output, profile, args.revision, artifacts)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print(json.dumps({"status": "error", "code": "INVALID_NATIVE_CAPTURE"}))
        return 2
    print(json.dumps({"status": "packed", "manifest_digest": bundle.manifest_digest}))
    return 0


def plan_command(args: argparse.Namespace) -> int:
    try:
        repo, output = args.repo.resolve(), args.output.resolve()
        if (
            output.is_relative_to(repo)
            or output.is_relative_to(args.bundle.resolve())
            or output == args.profile.resolve()
        ):
            raise QueryError("report overlaps input evidence")
    except (OSError, ValueError):
        print(json.dumps({"status": "error", "code": "INVALID_OUTPUT"}))
        return 2
    try:
        head = parse_tree(verify_checkout(repo, args.head))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        # Full execution on a dirty or wrong checkout is not a valid check of the
        # requested PR. Require the caller to restore that revision or fail CI.
        print(json.dumps({"status": "error", "code": "UNVERIFIED_NATIVE_CHECKOUT"}))
        return 2
    try:
        base = parse_tree(revision_tree(repo, args.base))
        profile = parse_profile(read_bounded(args.profile, MAX_MANIFEST_BYTES))
        bundle = load(args.bundle, args.expected_digest, profile)
        if (
            parse_tree(revision_tree(repo, bundle.manifest.anchor_commit))
            != bundle.anchor
        ):
            raise QueryError("map revision tree mismatch")
        report = bundle.plan(
            base,
            head,
            must_run=tuple(args.must_run),
            execution_mode=args.execution_mode,
        )
        report.pop("digest")
        report["comparison"] = {"base": args.base, "head": args.head}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        # A missing inventory cannot identify every full-suite test. The wildcard
        # is authoritative here, not a fabricated list of selected identifiers.
        report = {
            "schema_version": "smartci.bazel-bundle-plan.v1",
            "mode": "full",
            "patterns": ["..."],
            "fallback": ["MISSING_INVALID_OR_INCOMPATIBLE_NATIVE_EVIDENCE"],
            "production_omission_authorized": False,
            "requires_independent_full_control": args.execution_mode == "paired",
        }
    report["digest"] = sha256(canonical(report))
    try:
        atomic_write(output, canonical(report).decode())
    except OSError:
        print(json.dumps({"status": "error", "code": "REPORT_WRITE_FAILED"}))
        return 2
    print(
        json.dumps(
            {
                "status": "planned",
                "mode": report["mode"],
                "fallback": report["fallback"],
            }
        )
    )
    return 0


def command(args: argparse.Namespace) -> int:
    if args.bazel_command == "collect":
        try:
            if (args.reuse_bundle is None) != (args.expected_digest is None):
                raise QueryError(
                    "cache path and authenticated digest required together"
                )
            config = read_config(args.config)
            report = collect(
                args.repo.resolve(),
                args.revision,
                config,
                args.output.resolve(),
                reuse=args.reuse_bundle.resolve() if args.reuse_bundle else None,
                expected_digest=args.expected_digest,
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
        ):
            print(json.dumps({"status": "error", "code": "INVALID_COLLECTION_REQUEST"}))
            return 2
        print(json.dumps(report), flush=True)
        return 0 if report["status"] == "ready" else 1
    if args.bazel_command == "pack":
        return pack_command(args)
    return plan_command(args)
