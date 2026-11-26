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

The example enrollment workflow runs on an isolated GitHub runner and checks
missing-map rebuilding followed by compatible reuse. Hosted verification is
pending. Enrollment runs are not new PR-savings comparisons.

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
