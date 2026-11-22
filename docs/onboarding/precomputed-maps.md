# Validated precomputed TypeScript base maps

This is an opt-in base-map cache. Changed PR code still gets fresh native test
inventory and compiler discovery. The implementation is published in
[Smart CI PR #3](https://github.com/SharmaKunal14/smart-ci/pull/3), runtime commit
`fa7cb1994b98f0c2ddd0e83dd603eb9d127f6f41`. Nothing is merged or deployed to AWS.

## Trust and invalidation

The producer runs on pushes to explicitly enrolled, maintainer-controlled base
branches. `typescript scan` must produce a complete map with two independent
native inventory passes. The pilot publisher template pins every action and the
Smart CI commit, uses a read-only token, and retains its artifact for seven days.
Production enrollment must control who can write the approved base branch and
CI configuration; an arbitrary PR cannot declare itself a trusted publisher.

A separate fetch job executes no application code. The standard-library adapter
`scripts/fetch_typescript_map.py` verifies:

- The publisher workflow bytes at the exact requested base commit match the
  approved template rendered with the pinned Smart CI repository/commit.
- The producer is a successful completed push from the expected repository,
  branch and commit, with matching workflow path and artifact attempt.
- The artifact is unique, unexpired and at most seven days old; its archive
  checksum matches GitHub metadata. Size is bounded at 32 MiB and the archive
  must contain exactly `head-map.json`. Paths are never extracted from the ZIP.

Only then does it publish the payload digest as a GitHub job output. The PR job
receives the map separately. Its CLI checks byte integrity, snapshot integrity,
repository and actual merge-base identity, complete graph/inventory consistency,
tracked owners, configuration, unchanged manifests/lockfile, and compatibility
with fresh head provenance. That includes the entire runtime implementation,
TypeScript, Vitest, Node, Python, Pydantic, platform and machine identities.

Missing, malformed, tampered, stale or incompatible evidence reconstructs the
base from source. If reconstruction is unavailable, the independent full suite
runs. Old/new edge union, conservative widening, native settings, reviewed-skip
rules, must-run policy and sticky observed failures remain. A cache does not
make static analysis universally complete, nor sandbox repository configuration
or test execution. A compromised trusted publisher/runner is outside this trust
boundary. A checksum supplied by an untrusted PR is not authentication.

The optional run flags are `--base-map PATH --base-map-sha256 VERIFIED_DIGEST`.
The path must be outside the application checkout and the digest must come from
trusted CI provenance verification, never a PR-controlled manifest. `run.json`
and the Markdown audit disclose cache hit/miss status and reconstruction reason.
No flags means normal reconstruction. No paid model or AWS service is involved.

## Real GitHub verification

Before opening the fix PR, GitHub successfully produced maps for the buggy base
and fixed branch. Producer jobs took **30s and 33s**, respectively; these are
separate costs, not free work removed from the accounting.

[Fix PR #7](https://github.com/SharmaKunal14/date-fns/pull/7) changes only the
three real upstream month-parsing production files. Its workflow checks out the
actual PR merge revision. Native settings and tests are unchanged. Three
[hosted attempts](https://github.com/SharmaKunal14/date-fns/actions/runs/44915242036)
produced these medians:

| Measurement | Native full | Rebuild maps | Validated cache |
| --- | ---: | ---: | ---: |
| Planning | — | 6.42s | 2.57s |
| Test command including planning/startup | 2.88s | 10.13s | 5.54s |
| Test job alone | 23s | 37s | 34s |
| Workflow trigger to job result | **27s** | **39s** | **58s** |
| Test files / cases | 253 / 3,167 | 4 / 19 | 4 / 19 |

The cache path additionally waited for its authenticated fetch/transfer job,
which took **18s median**, and dependent-job dispatch. Comparing only 34s with
37s would hide that waiting. **Planning improved by about 60%, but this integration
made end-to-end PR latency worse.** Earlier measurements were 21s native / 35s
optimized Smart CI per complete job; runner variation remains visible. None of
these results demonstrates a production speed or billing benefit.

Every passing cached run was a validated hit, with no reconstruction/fallback or
retry. Its graphs and complete selection JSON matched the fresh-rebuild control.
All 15 timezone-script executions passed in each job; full execution retained 19
reviewed skips, and the subset had none.

[Defect PR #8](https://github.com/SharmaKunal14/date-fns/pull/8) deliberately
restored the historical bug. Its [run](https://github.com/SharmaKunal14/date-fns/actions/runs/44915524573)
correctly remained red. Cached and rebuilt selections each ran four files / 19
cases and caught exactly the same six failure IDs as the 253-file / 3,167-case
native run. Cached execution was a validated hit with no fallback or retry, and
the failure gate retained every observed failure. This is one historical defect,
not a universal recall guarantee.

The [GitHub safety workflow](https://github.com/SharmaKunal14/smart-ci/actions/runs/44915105514)
passed all **289 tests**, formatting/lint/type checks, and source/wheel builds.
Tests cover producer forgery, wrong workflow definition, wrong revision or
repository, expired/future artifacts, archive tampering, duplicate entries, unsafe
paths, stale environment/tool identity, failed reconstruction and credential
separation. Exact measurements are saved in
[`date-fns-precomputed-2026-11-22.json`](../benchmarks/date-fns-precomputed-2026-11-22.json).

## Verification and reproduction

Open the comparison run, select attempts 1–3, and inspect `fetch-map`,
`timing (native)`, `timing (rebuild)` and `timing (cached)`. Compare timestamps
from the same attempt start, including the cached job's dependency wait. Inspect
its uploaded receipt, `command-time.json`, selection and run reports. The defect
run must show six retained failures and a red failure gate. A green full fallback
must never be counted as a cache-hit selective speedup.

The publisher is `examples/date-fns/precompute.yml.in`; the bounded comparison is
rendered by `scripts/render_precomputed_benchmark.py`. Adapt their explicit repo
and branch enrollment before using another repository. All actions and the tool
must remain pinned. Missing map permissions or expired artifacts should degrade
to reconstruction, not bypass verification. No AWS deployment steps are needed.

## Recommended direction, not yet implemented

Keep the fail-open behavior, but remove the separate blocking retrieval pipeline
from a future production design. Reuse the existing test job's environment, make
selection cheap enough to justify itself, and investigate authenticated map
transport that does not add a second runner startup and artifact re-upload.
Any replacement must retain the provenance boundary rather than merely moving
an unchecked map into the application job.

Next evaluate an incremental collector only for explicitly supported changes:
retain old edges, update affected relationships, and revalidate inventory and
resolution context. Configuration, dynamic behavior and uncertain invalidation
still require broad analysis or full tests. A deterministic cost gate should
choose full execution when selection overhead cannot recover its cost. Measure
an existing expensive integration/browser/database suite without slowing tests
artificially. These are proposed directions, not established performance wins.
