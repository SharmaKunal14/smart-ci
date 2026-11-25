# Portable Bazel evidence and planning

`smartci bazel pack` and `smartci bazel plan` expose the native graph planner through
the installed CLI. Their implementation contains no Abseil repository, workflow
run or benchmark-record constants. This is a reusable evidence boundary, not yet
automatic native collection, cache refresh or execution for arbitrary projects.
The supported change model is the reviewed C++ declaration model used by the
existing native selector: only existing declared `.cc`/`.h` modifications can
reuse the graph. Other changes retain the full native command.

## Trusted capture and profile

A reviewed collector must first run the complete native test command and the
unconfigured `deps(//...)`/`//...` queries in the intended toolchain. It must bind
the capture to the exact repository commit and profile. These commands execute
repository-owned build logic; the pack/plan commands below only read captured
evidence and Git objects. Do not treat a graph suggested by a model as native
collector output.

The profile follows `schemas/bazel-profile.v1.json`:

| Field | Meaning |
|---|---|
| `repository` | Expected repository identity, supplied by trusted CI policy. |
| `bazel_version` | Exact released Bazel version recorded in the native event stream. |
| `command_digest` | SHA-256 of the reviewed native command descriptor. The collector, not this packer, must verify that it executed that command. |
| `options_digest` | SHA-256 of the full capture's `started.optionsDescription` string. Packing checks this against the event bytes. |
| `environment_digest` | SHA-256 of the reviewed container/toolchain/environment descriptor. The collector must verify that environment; a supplied digest is not runtime attestation. |
| `query_mode` | `unconfigured-deps-all`; retain all declared branches and tool dependencies. |
| `change_model` | `reviewed-declared-cpp-inputs-v1`; an explicit compatibility assumption, not inferred proof of hermetic runtime access. |

Use profile policy from the protected enrollment configuration, not a replacement
submitted in the PR being evaluated. The commands do not inspect credentials or
contact a model/provider. Captures must be approved for retention and produced
without secrets in command-line arguments or environment diagnostics.

## Package one validated capture

Start from the clean repository root checked out at the capture's exact commit.
Put capture inputs and output outside that repository. For example, with variables
set by the trusted collector:

```sh
smartci bazel pack \
  --repo "$REPOSITORY_ROOT" --revision "$CAPTURE_COMMIT" \
  --profile "$TRUSTED_PROFILE" \
  --query "$CAPTURE_DIR/query.xml" --roots "$CAPTURE_DIR/roots.txt" \
  --native-bep "$CAPTURE_DIR/native.bep.json" \
  --output "$NEW_BUNDLE_DIR"
```

The command rejects a dirty/different checkout, non-commit revisions, malformed or
incomplete native events, failed/flaky references, non-root or subset target
patterns, mismatched native version/options, invalid dependency closure and
inconsistent native target scope. Query source paths must exist in the captured
Git tree. All original build-only targets and configurations are retained.

It writes four bounded evidence files and a canonical manifest, publishing the
manifest last. Existing directories are never overwritten. Its JSON receipt
contains `manifest_digest`, the SHA-256 of the exact canonical manifest bytes.
The manifest binds the repository/profile, anchor commit and every artifact.

**The receipt is an integrity identifier, not authentication.** Trusted CI must
retain it with verified run/commit/tool provenance. Reading a digest from the same
untrusted download does not authenticate that download. The packer cannot prove
that arbitrary supplied XML/BEP files honestly describe the declared capture.

## Plan each PR

Check out the exact PR head with the base and map-anchor commit objects available.
Acquire a trusted compatible bundle and its independently authenticated digest:

```sh
smartci bazel plan \
  --repo "$REPOSITORY_ROOT" --base "$BASE_COMMIT" --head "$HEAD_COMMIT" \
  --profile "$TRUSTED_PROFILE" --bundle "$BUNDLE_DIR" \
  --expected-digest "$VERIFIED_MANIFEST_DIGEST" \
  --execution-mode selective --output "$REPORT_PATH"
```

Omit `--execution-mode selective` to retain the default paired evaluation policy.
That policy must come from the reviewed CI entrypoint; a model or PR-supplied
report cannot grant authority. Repeat `--must-run //package:test` for required
native test targets. Unknown mandatory targets retain full fallback.

The CLI checks profile equality, artifact hashes, native completeness, clean head
identity and the anchor's actual Git tree. It then applies the existing conservative
selector to both base and head trees. Its digest includes the bundle identity,
profile, revisions, dependency witnesses, selected targets, full-fallback reasons
and execution policy. Timings and output paths do not enter the plan.

For a valid subset, `patterns` starts with `...` and subtracts only omitted test
targets, preserving build-only work. A full fallback has `patterns: ["..."]`.
If the inventory cannot be trusted, the report deliberately has no `selected`
list: the independent full command defines execution. Never interpret a missing
list as permission to run zero tests.

`plan` writes a full fallback and exits 0 for missing, invalid, stale or incompatible
map evidence. A dirty, wrong or unverifiable head checkout exits 2: running all
tests on the wrong source is not verification of the requested PR. The caller must
restore and verify the correct checkout before any full execution, or fail CI.
Exit 2 also covers invalid invocation or failure to write a usable report; never
reuse an older report after a nonzero exit. Neither
command executes the proposed tests. The execution adapter must still preserve
native failures and reconcile actual test/build results.

## Verification and remaining work

Safety tests cover manifest/artifact tampering, wrong repository/profile, incomplete
or selective native references, duplicate keys, special files, dirty checkouts,
wrong revisions, output overlap, stable plans and full fallback. The packaged event
reader and preserved standalone benchmark reader run the same adversarial event
cases; the old copied CI harness remains usable without installing Smart CI.

`scripts/verify_bazel_bundle.py` and `.github/workflows/bazel-bundle.yml` verify this
CLI against authenticated existing GitHub captures and exact Abseil PR revisions.
The verifier compares identities/configurations with previously recorded native
outcomes and repeats plans byte-for-byte. It does not execute new native tests or
claim a new performance measurement. The repository/run pins belong to that test
harness, not the reusable CLI implementation.

The first [hosted replay](https://github.com/SharmaKunal14/smart-ci/actions/runs/45561199771)
passed on [PR #16](https://github.com/SharmaKunal14/smart-ci/pull/16). It reproduced
2/252 targets for the localized change, the same two compilation-failure targets
for the regression, 251/252 for the shared dependency, and all 252 after a build
change. Each retained all 324 build-only targets, matched recorded configuration
identities and repeated byte-for-byte. Altering an evidence artifact required full
execution. The [record](../benchmarks/bazel-bundle-replay-2026-11-25.json) binds
the tested tool commit and output hashes. These are planning checks against prior
native outcomes, not new native test runs or evidence of additional time savings.

The hosted verifier downloads pinned historical artifacts. It will fail when those
artifacts expire or disappear; it must not silently substitute a different run.
This bounded evaluation workflow is not the production artifact retention or
refresh mechanism.

Automatic collector orchestration, protected artifact publication/acquisition,
refresh after build/test inventory changes, execution integration and representative
warm-cache evaluation remain unfinished. Missing bundles currently request full
execution; this CLI does not silently rebuild one or promote untrusted evidence.
