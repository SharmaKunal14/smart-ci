# Automatic native collection and refresh

`smartci bazel collect` orchestrates the full native command and dependency query
from a trusted `bazel-capture.v1.json` configuration. The configuration binds the
profile, two argument arrays and bounded timeouts. Commands use an absolute
executable; `{repo}` and `{capture}` are substituted as literal arguments, never
evaluated by a shell. The native command writes `native.bep.json`; the query writes
`query.xml`, `roots.txt` and `bazel-version.txt` under the capture directory.

```sh
smartci bazel collect \
  --repo "$REPOSITORY_ROOT" --revision "$CAPTURE_COMMIT" \
  --config "$TRUSTED_CAPTURE_CONFIG" --output "$NEW_COLLECTION_DIR" \
  --reuse-bundle "$CACHED_BUNDLE_DIR" --expected-digest "$VERIFIED_MANIFEST_DIGEST"
```

Omit both reuse arguments for the initial scan. A missing, tampered, incompatible
or stale supplied bundle triggers fresh full execution and graph collection. A
compatible bundle is copied only after validating its profile, command-config
digest, artifact identities, anchor tree and reuse eligibility at the requested
revision. Source-only reuse preserves the existing declared C++ change model;
build-definition and inventory changes require collection. Reuse keeps the
original map revision and does not pretend that native tests ran again. Older
bundles without a capture-config digest remain usable by `plan`, but `collect`
rebuilds them rather than assuming which commands originally produced them.

The collector checks the checkout before and after execution, validates complete
passing native results before running the query, rejects a different query
toolchain, and prevents the query from replacing native results. Publication
happens only after the bundle validates. `collection.json` records `status`,
`cache`, native/query exits, revision, config digest and manifest digest. Require
both exit 0 and `status: ready`; a failed collection is never permission to skip
tests or consume a partial bundle. No automatic retries are made.

The reviewed Abseil adapter in `examples/abseil/collection_driver.py` preserves its
native container/compiler/test profile and performs fresh commands without saved
benchmark inventories or run IDs. `capture-profile.json` binds that one supported
profile. Generate its configuration with:

```sh
uv run --frozen python examples/abseil/collection_driver.py configure \
  --profile examples/abseil/capture-profile.json --output "$TRUSTED_CAPTURE_CONFIG"
```

The example enrollment workflow is intended for an isolated GitHub runner and
checks missing-map rebuilding followed by compatible reuse. It supports a bounded
PR trigger and an explicit dispatch restricted to the reviewed enrollment branch.
Enrollment runs are not new PR-savings comparisons.

[Smart CI PR #17](https://github.com/SharmaKunal14/smart-ci/pull/17) passed all
727 tests, formatting, lint, strict types and source/wheel builds in
[GitHub run 45751951089](https://github.com/SharmaKunal14/smart-ci/actions/runs/45751951089).
Those tests include real subprocess handling with synthetic native evidence;
they do not replace a fresh native enrollment run.

[Abseil PR #12](https://github.com/SharmaKunal14/abseil-cpp/pull/12) remains unmerged
and has no enrollment run. The current workflow is `.github/workflows/smartci-native-query.yml`,
on the isolated `codex/native-collection-base` and `codex/native-collection-onboarding`
branches. Native source and tests are unchanged. GitHub's dispatch API returned
HTTP 422, “Actions has been disabled for this repository,” before and after
reapplying the repository's enabled setting. Its permissions API simultaneously
reported enabled=true. The cause of that inconsistent service state is unresolved.
Reopen/synchronize events, the existing workflow path, and matching base/head
definitions did not create a run. Follow GitHub's
[workflow troubleshooting guidance](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
and inspect the fork's Actions UI before retrying; do not treat an absent check
as a successful collection. Once activation is resolved, trigger this one bounded
workflow and verify `enrollment/collection.json`, `enrollment/bundle/manifest.json`,
the native event stream, and `reused/collection.json` in `native-enrollment-1`.

The [status record](../benchmarks/bazel-collection-2026-11-26.json) separates the
successful tool checks from the unexecuted native experiment. No onboarding
duration, selective-execution result or new savings claim is available yet.

Source-scope clarification: "unchanged" means relative to this enrollment PR's
own base. That base is the pre-fix side of the earlier localized experiment and
differs from the previous standalone native performance baseline in
`absl/container/internal/raw_linked_hash_set.h`. The collector must establish its
own complete passing native evidence; previous timing/results cannot substitute
for this run.

Collection executes build logic and tests. Use protected configuration and an
isolated runner without persisted credentials. Only PATH, HOME, LANG and TMPDIR
are inherited; environment filtering is not filesystem isolation. Adapters must
bound their logs and clean external resources such as Docker containers. The
collector bounds POSIX process groups and validates output after commands finish;
it cannot constrain arbitrary repository filesystem writes by itself. Failed
commands retain redacted stage/error codes; the reviewed adapter retains bounded
native logs separately for diagnosis.

This implements collection and compatibility-driven refresh. It does not yet
discover trusted GitHub artifacts automatically, publish an authenticated catalog,
or execute a PR's selected plan. Those integration steps remain required for the
complete product. A map or receipt supplied by the PR is not trusted merely
because its hashes match.
