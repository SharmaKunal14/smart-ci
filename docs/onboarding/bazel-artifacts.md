# Discovering trusted native maps on GitHub

`smartci bazel fetch` finds a map for an exact revision without a configured run
ID. It consumes a reviewed publisher policy and the same capture configuration
used by `smartci bazel collect`. This is artifact discovery and validation, not
test execution or evidence of a speed improvement.

The policy identifies the repository, publisher branch, workflow path, SHA-256
of the approved workflow bytes, event, artifact prefix and maximum age. Export
its contract with `smartci schema bazel-publisher`. The default event is `push`;
`workflow_dispatch` can be explicitly approved. Pull-request events cannot be
trusted publishers. Policy and configuration must come from protected CI control
files or a pinned, reviewed tool revision, never from the PR under test.

Example policy shape (replace the digest with the hash of the reviewed workflow):

```json
{
  "schema_version": "1",
  "repository": "example/project",
  "branch": "main",
  "workflow": ".github/workflows/native-maps.yml",
  "workflow_digest": "<64 lowercase hexadecimal characters>",
  "event": "push",
  "artifact_prefix": "native-enrollment",
  "max_age_seconds": 604800
}
```

Review the publisher's checkout, pinned collector, command configuration, native
profile, and upload path before approving its hash. In particular it must check
out the run's exact commit and must not accept arbitrary revision or command
overrides through dispatch inputs. Matching a workflow hash authenticates that
reviewed definition; it does not prove an unsafe definition is trustworthy or
enforce branch protection. Restrict who can change the publisher and its inputs.

## Publisher and consumer contract

The publisher runs the existing collector and uploads one artifact named
`<artifact_prefix>-<github.run_attempt>`. Its ZIP must contain:

```text
enrollment/collection.json
enrollment/bundle/manifest.json
enrollment/bundle/query.xml
enrollment/bundle/roots.txt
enrollment/bundle/native.bep.json
enrollment/bundle/anchor.tree
```

This matches the Abseil enrollment example. Other bounded diagnostic files are
permitted but are never extracted. A ready receipt, complete passing native
evidence, consistent graph/root inventory and matching capture configuration are
required. A reused collection preserves its original map revision and records
that no native commands were rerun.

Run retrieval in a separate job that executes only pinned Smart CI code, with
`contents: read` and `actions: read`. Use its scoped GitHub token as `GH_TOKEN`;
do not give the native collection/test job a retrieval token or persisted Git
credentials. GitHub documents the read permission and artifact metadata in its
[artifact API](https://docs.github.com/en/rest/actions/artifacts).

```sh
smartci bazel fetch \
  --publisher "$TRUSTED_PUBLISHER_POLICY" \
  --revision "$BASE_COMMIT" \
  --config "$TRUSTED_CAPTURE_CONFIG" \
  --output "$NEW_FETCH_DIR"
```

Exit 0 plus `fetch.json` with `status: ready` supplies a verified `bundle/` and
`manifest_digest`. The receipt also records the discovered run, attempt, artifact,
archive hash, publisher-policy hash and requested/map revisions. Preserve this
receipt with the bundle through trusted CI artifact transport; don't replace
its digest with a PR-supplied value.

On exit 2, treat the result as a cache miss. No successful receipt is supplied.
In the isolated native job, call `smartci bazel collect` without reuse arguments
to build fresh evidence; or run the independent full suite if rebuilding is not
appropriate. A retrieval failure never means an empty test plan. On a hit,
pass the verified bundle and manifest digest to `collect` using `--reuse-bundle`
and `--expected-digest`. The collector still checks the actual Git anchor tree
and change eligibility. Then `smartci bazel plan` checks the exact PR checkout and
produces a subset or conservative full fallback. Retrieval alone never authorizes
omissions.

## Validation and limits

Discovery checks the exact workflow bytes at the requested commit and the run's
repository, head repository, commit, branch, workflow, event, successful completion
and attempt. It checks artifact origin, age/expiry, GitHub's archive digest,
canonical manifest, profile, command-config digest, receipt and all evidence
members. Neither a valid checksum nor a green PR run alone establishes trust.

It reads at most 20 run entries, inspects at most three matching runs, and checks
up to 100 artifacts per run. Each API request has a 45-second deadline. Metadata
is capped at 2 MiB, archives at 64 MiB, declared expanded contents at 256 MiB and
entries at 256. Required files have individual limits. Duplicate keys/names,
path traversal, symlinks, encrypted entries and oversized members are rejected.
No shell or repository code is executed; API errors are redacted.

This first transport searches only the requested revision. It does not search
ancestor commits, publish maps itself, create a catalog, or wire an entire PR
runner automatically. Capture configurations include executable/script paths:
keep those stable between producer and consumer. A changed path or toolchain
requires a rebuild even if a human thinks it is equivalent. This conservative
tradeoff avoids silently reusing evidence under different commands.

Focused transport tests exercise origin mismatches, PR-origin rejection, expired
or tampered artifacts, archive bounds, failed collection receipts, profile/command
changes, subprocess time/output limits and redacted misses. The existing full
safety workflow runs these tests and the package build on each tool PR. These
tests use controlled API responses and synthetic native evidence. The
[fresh Abseil publisher passed](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45764627612);
the separate consumer workflow in `.github/workflows/native-map-handoff.yml` now
checks discovery without a configured run ID, stable receipts, actual source-tree
binding, compatible reuse, repeated plans for historical PRs #10/#11, preservation
of all build-only targets, and full fallback for tampered evidence. Its result
remains pending until that hosted run completes. It does not execute native tests
or measure a new PR speedup.

The verifier binds the reviewed Linux producer's exact command paths, including
`.venv/bin/python3`, independently of the consumer's interpreter and workspace.
Generating a new consumer-local configuration would correctly fail the command
identity check. The expected configuration is constructed from reviewed inputs,
not accepted from the downloaded artifact. No command identity check is relaxed.
