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
checks missing-map rebuilding followed by compatible reuse. It publishes on
pushes to `codex/native-collection-onboarding` in the reviewed Abseil fork only,
with one 35-minute job. This push trigger can produce a trusted map before later
PRs need it. It does not require merging a PR or a manual-dispatch definition on
the default branch. Enrollment runs are not new PR-savings comparisons.

[Smart CI PR #17](https://github.com/SharmaKunal14/smart-ci/pull/17) passed all
727 tests, formatting, lint, strict types and source/wheel builds in
[GitHub run 45751951089](https://github.com/SharmaKunal14/smart-ci/actions/runs/45751951089).
Those tests include real subprocess handling with synthetic native evidence;
they do not replace a fresh native enrollment run.

[Abseil PR #12](https://github.com/SharmaKunal14/abseil-cpp/pull/12) remains unmerged
and its [native enrollment run passed](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45764627612)
at head `622fd1c2829655d595ffeca8656382ff305a5ddb`. The full native command passed
252 test targets and retained all 324 build-only targets. Fresh collection produced
2,614 nodes, 13,349 edges, 1,504 source paths and 588 query roots. A deliberately
missing bundle was rebuilt; the subsequent compatible collection reused the same
manifest without executing either command again.

The workflow took 661 seconds from creation to completion (657 runner seconds).
Its native command took 623.67 seconds and its query 9.33 seconds. These are initial
enrollment costs, not a new selective-PR comparison. The current workflow is
`.github/workflows/smartci-native-query.yml`,
on the isolated `codex/native-collection-base` and `codex/native-collection-onboarding`
branches. The initial setup mistakenly inherited the intentionally broken source
used by the earlier regression experiment. The current head restores the exact
application/test/build inputs of passing native baseline `6da46d213f16f99b80f57f9d861792bb793923a9`;
the only application change relative to this PR's base is `.first` to `.position`
in `raw_linked_hash_set.h`. No tests or native settings were weakened, and earlier
regression evidence remains intact.

GitHub's earlier dispatch API returned
HTTP 422, “Actions has been disabled for this repository,” before and after
reapplying the repository's enabled setting. Its permissions API simultaneously
reported enabled=true. The cause of that inconsistent service state is unresolved.
Further inspection also found GitHub marked the PR `CONFLICTING/DIRTY`. Reparenting
its identical file tree onto the current base cleared that state; GitHub then
reported `MERGEABLE/CLEAN`. A new reopen event still created no run. The workflow
now uses the bounded push publisher above instead of PR/manual triggers. A later
reviewed push produced the successful run above. The exact cause of the earlier
activation inconsistency remains unknown; success does not establish which
setting or service change resolved it. A reviewed push to the enrollment branch
triggers the single bounded workflow. Reopening PR #12 is no
longer its trigger. Verify `enrollment/collection.json`, `enrollment/bundle/manifest.json`,
the native event stream, and `reused/collection.json` in `native-enrollment-1`.

The [enrollment evidence](../benchmarks/bazel-enrollment-2026-11-26.json) records the
GitHub run, fresh/reuse receipts, scope, timings and artifact hashes. The earlier
[blocked status record](../benchmarks/bazel-collection-2026-11-26.json) is retained
as historical evidence. There is still no new selective-execution or savings
claim for this collector.

The collector must establish its own complete passing native evidence. Matching
the earlier baseline's source inputs does not transfer its outcome or timing to
this new enrollment run.

Collection executes build logic and tests. Use protected configuration and an
isolated runner without persisted credentials. Only PATH, HOME, LANG and TMPDIR
are inherited; environment filtering is not filesystem isolation. Adapters must
bound their logs and clean external resources such as Docker containers. The
collector bounds POSIX process groups and validates output after commands finish;
it cannot constrain arbitrary repository filesystem writes by itself. Failed
commands retain redacted stage/error codes; the reviewed adapter retains bounded
native logs separately for diagnosis.

This implements collection and compatibility-driven refresh. The separate
[`smartci bazel fetch` command](bazel-artifacts.md) discovers compatible artifacts
from a reviewed GitHub publisher without hard-coded run IDs. Its transport checks
are tested with controlled API responses. Fresh native publication is now
verified, as is [separate hosted retrieval and consumption](https://github.com/SharmaKunal14/smart-ci/actions/runs/45767540576).
The consumer reproduced historical subset/full plans and tampered-map fallback;
it did not execute new native tests. Complete PR runner integration remains
required. A map or receipt
supplied by the PR is not trusted merely because its hashes match.
