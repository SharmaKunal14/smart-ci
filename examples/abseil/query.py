"""Collect and audit a real Bazel graph; never execute a proposed subset."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from baseline import summarize_events
from diagnostics import (
    PROFILE_SHA256,
    UPSTREAM,
    run_profile,
    targeted_profile,
    verify_source,
)

from smartci.bazel.audit import native_inventory, reconcile_graph
from smartci.bazel.graph import MAX_XML_BYTES, QueryError, label, parse_query_xml

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/benchmarks/abseil-apport-baseline-2026-11-23.json"
)


def bounded_read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise QueryError("artifact exceeds size limit")
    return data


def query_profile(raw: bytes) -> bytes:
    targeted_profile(raw, "full")  # Reject any unreviewed native profile drift.
    start = b"          /usr/local/bin/bazel test ..."
    finish = b'            ${BAZEL_EXTRA_ARGS:-}"'
    if raw.count(start) != 1 or raw.count(finish) != 1:
        raise QueryError("ambiguous native command boundary")
    prefix, command = raw.split(start)
    _, suffix = command.split(finish)
    # Query is unconfigured: it deliberately includes every select branch. Native
    # execution eligibility is reconciled from a separate complete full run.
    commands = b"""          set -eu
          /usr/local/bin/bazel --version > /evidence/bazel-version.txt
          /usr/local/bin/bazel query 'deps(//...)' --enable_bzlmod=true --output=xml --order_output=full --noxml:line_numbers > /evidence/query.xml
          /usr/local/bin/bazel query '//...' --enable_bzlmod=true --output=label --order_output=full > /evidence/roots.txt
          /usr/local/bin/bazel query 'buildfiles(deps(//...))' --enable_bzlmod=true --output=label --order_output=full > /evidence/buildfiles.txt\""""
    return prefix + commands + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-bep", type=Path, required=True)
    args = parser.parse_args()
    root, output = Path.cwd().resolve(), args.output.resolve()
    if output.is_relative_to(root) or any(
        char not in "/._-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for char in str(output)
    ):
        parser.error("new external output directory with simple path required")
    verify_source(root)
    reference = json.loads(bounded_read(REFERENCE, 1024 * 1024))
    native_bytes = bounded_read(args.baseline_bep, 64 * 1024 * 1024)
    if (
        reference["upstream"] != UPSTREAM
        or reference["native"]["profile_sha256"] != PROFILE_SHA256
        or hashlib.sha256(native_bytes).hexdigest()
        != reference["artifact_sha256"]["native-resource-baseline/native.bep.json"]
    ):
        raise QueryError("native reference identity mismatch")
    inventory = native_inventory(summarize_events(args.baseline_bep))
    profile = query_profile(
        (root / "ci/linux_gcc-latest_libstdcxx_bazel.sh").read_bytes()
    )
    output.mkdir(parents=True, exist_ok=False)
    script = output / "query-native.sh"
    script.write_bytes(profile)
    name = "smartci-query-" + uuid.uuid4().hex
    # Artifact credentials are scoped to an earlier workflow step. Do not pass
    # workflow/model credentials into repository-owned build definitions.
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR")
        if key in os.environ
    }
    environment.update(
        {
            "ABSEIL_ROOT": str(root),
            "STD": "c++17",
            "COMPILATION_MODE": "fastbuild",
            "EXCEPTIONS_MODE": "-fno-exceptions",
            "DOCKER_EXTRA_ARGS": f"--name {name} --mount type=bind,source={output},target=/evidence",
        }
    )
    print(
        "Collecting declared Bazel graph in the native pinned toolchain...", flush=True
    )
    started = time.monotonic()
    try:
        code, elapsed, error = run_profile(script, output, environment, timeout=600)
    except (OSError, ValueError, subprocess.SubprocessError):
        code, elapsed, error = 125, time.monotonic() - started, "QUERY_COMMAND_FAILED"
    if code in {124, 125} or code < 0:
        try:
            subprocess.run(
                ["docker", "rm", "--force", name],
                check=True,
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            error = "QUERY_CONTAINER_CLEANUP_FAILED"
    report: dict[str, object] = {
        "schema_version": "smartci.native-graph-audit.v1",
        "upstream": UPSTREAM,
        "native_reference_run": reference["run"],
        "native_profile_sha256": PROFILE_SHA256,
        "query_profile_sha256": hashlib.sha256(profile).hexdigest(),
        "command_seconds": elapsed,
        "exit_code": code,
        "error": error,
        "omission_authorized": False,
        "test_execution": "none",
        "model_calls": 0,
    }
    try:
        if code != 0 or error:
            raise QueryError("native query command did not complete")
        if bounded_read(output / "bazel-version.txt", 256).strip() != b"bazel 9.1.0":
            raise QueryError("unexpected query toolchain version")
        xml = bounded_read(output / "query.xml", MAX_XML_BYTES)
        graph = parse_query_xml(xml)
        roots = (
            bounded_read(output / "roots.txt", 4 * 1024 * 1024).decode().splitlines()
        )
        definitions = (
            bounded_read(output / "buildfiles.txt", 4 * 1024 * 1024)
            .decode()
            .splitlines()
        )
        if not definitions or len(definitions) > 100_000:
            raise QueryError("empty or excessive build definition set")
        report["audit"] = reconcile_graph(graph, roots, inventory)
        report["build_definitions"] = sorted({label(value) for value in definitions})
        report["query_sha256"] = hashlib.sha256(xml).hexdigest()
        # Candidate categories were chosen from actual recent upstream changes
        # before inspecting graph breadth. These are audits, not PR selections.
        candidates = {
            "cord_optimization": ["absl/strings/cord.cc", "absl/strings/cord.h"],
            "span_const_regression": ["absl/types/span.h"],
            "linked_hash_regression": [
                "absl/container/linked_hash_map.h",
                "absl/container/linked_hash_set.h",
            ],
            "shared_hash": ["absl/hash/internal/hash.cc", "absl/hash/internal/hash.h"],
        }
        impacts = {}
        for candidate, paths in candidates.items():
            affected = graph.affected(paths)
            tests = sorted(set(affected) & set(inventory.tests))
            impacts[candidate] = {
                "paths": paths,
                "candidate_tests": tests,
                "witnesses": {test: affected[test] for test in tests},
            }
        report["candidate_impacts"] = impacts
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["error"] = error or "QUERY_EVIDENCE_INVALID"
        report["error_reason"] = (
            str(exc)
            if isinstance(exc, QueryError)
            else "bounded artifact validation failed"
        )
    (output / "audit.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {key: report[key] for key in ("exit_code", "error", "omission_authorized")}
        ),
        flush=True,
    )
    return 1 if code != 0 or report["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
