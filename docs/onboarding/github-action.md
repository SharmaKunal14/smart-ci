# Native GitHub Action (alpha)

The Action runs the reusable Smart CI CLI on the customer's GitHub runner. It
installs a pinned, checksum-verified release and its hash-pinned dependencies,
derives the PR base/head from GitHub, retrieves approved dependency evidence or
rebuilds it, then invokes the supported native tests. No CLI service, AWS account,
model credential or paid model call is involved.

This release starts with the existing reviewed Bazel contract. The bundled
`abseil-gcc-cpp17-v1` adapter is specifically for Abseil's pinned GCC/C++17
fastbuild profile, including its native image, flags and build-event validation.
It is **not** a general adapter for every Bazel repository. A different native
profile needs reviewed capture/execution commands and evidence validation before
it may omit tests. Python/TypeScript pilots remain separate existing adapters.

## Customer workflow

Keep the repository's existing native environment setup. Replace its test step
with the Action; the Action installs the CLI itself. Pin `uses` to a reviewed
40-character Action commit. The release pin inside that commit also names the
exact wheel version and SHA-256. Do not use the moving development branch.

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
  actions: read
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
          persist-credentials: false
      # Preserve the existing native toolchain/environment preparation here.
      - uses: SharmaKunal14/smart-ci@e780aeb00eb5b81c35b062c65734067c03279754
```

For the bundled profile, `.smartci/native.json` starts as:

```json
{
  "schema_version": "1",
  "profile": "abseil-gcc-cpp17-v1",
  "maps": {"branch": "main", "workflow": ".github/workflows/tests.yml"}
}
```

Save the example workflow as `.github/workflows/tests.yml`; `maps.workflow`
must match its path, and `maps.branch` must be the reviewed/protected branch.
The sample pins the tested 0.2.0a2 Action commit. Its
[hosted safety gate](https://github.com/SharmaKunal14/smart-ci/actions/runs/45956316159)
passed all 1,153 tests, linting, typing, build and wheel-digest verification.
Do not point automatic-map configuration at the earlier 0.2.0a1 Action.

The preset ships the reviewed adapter, so customers do not copy scripts or install
the CLI. A push to the approved branch runs the complete native command and query,
validates the resulting map, and uploads `smartci-native-map-<attempt>`. The next
eligible PR retrieves it automatically. The Action derives the publisher's
repository and workflow digest from the trusted context and base-owned workflow;
customers do not assemble run IDs, workflow hashes or capture contracts manually.

Only a successful approved-branch workflow can supply a trusted map. The map
remains revision/profile/capture-bound and expires after seven days. A changed
Action pin or copied adapter invalidates incompatible capture identity. Missing,
pending, stale or rejected maps still cause reconstruction or full execution.
Enrollment requires a passing full native baseline: a failing branch publishes
no usable map. Protect the publisher branch and review workflow/policy changes.

This version performs a fresh full enrollment on each configured branch push.
Prefer integrating it into an existing full post-push job. If it adds an extra
full job, count that cost against PR savings; faster PRs alone do not establish
lower total compute. For N PRs sharing a map, compare `additional enrollment +
sum(Smart PR time)` with `sum(native PR time)`, using job duration for runner
compute. Do not charge the whole pre-existing full push job as a new cost, or
hide an additional full job when no such baseline job existed. A push followed
immediately by a PR may race unfinished enrollment and therefore rebuild. No claim of warm-cache savings is made.

Omitting `maps` retains the earlier reconstruct-or-full behavior. Advanced existing
`publisher`/`publisher_capture` contracts remain supported, but cannot be combined
with `maps`. See [artifact onboarding](bazel-artifacts.md) for that legacy interface.

For an already reviewed custom adapter, the full policy form accepts `capture`,
`execution`, `fallback`, optional `maps` or `publisher`/`publisher_capture`, and `files`.
It uses the [native Action policy schema](../../schemas/native-action-policy.v1.json).
Listed adapter files are loaded from the exact PR base into an external control
directory. `{control}` refers there, `{action}` to the pinned Action, `{repo}` to
the source checkout and `{capture}` to the invocation's evidence directory.
Commands are bounded argument arrays, not shell strings. The independent full
fallback must work without Smart CI or its Python dependencies installed.

## Trust and failure behavior

- Ordinary `pull_request` events and explicitly approved branch `push` enrollment
  are supported on disposable GitHub-hosted Linux x64 runners, with one invocation
  per non-matrix job. `pull_request_target`, tags, unrelated pushes and reusable
  workflow contexts are rejected. Do not expose private
  credentials or persist Git credentials before executing PR code.
- The source checkout must be the exact clean PR head, with the base commit
  available. Configuration and custom adapter files come from the base, so a PR
  cannot approve its own selection policy. Onboarding must first be reviewed on
  the base branch; a config introduced only in the PR is rejected.
- The Action's read-only token exists only in the evidence-retrieval step. The
  native child environment is allowlisted. This is not filesystem isolation;
  native build/test code executes on the runner with normal job privileges.
- Missing, stale or rejected evidence causes base reconstruction or full
  execution. Failure to restore the head stops the job. PR-produced maps are not
  published as trusted baselines.
- Installer or control-plane preparation failure runs the reviewed independent
  full command. Native failures are propagated, never retried to conceal a red
  result. Invalid PR context or missing/untrusted policy fails visibly before
  executing code, since no safe full command is known.
- Selection retains required build-only targets and mandatory tests. Unsupported
  file changes, build/configuration drift or evidence-integrity failures require
  full execution. A full run uses the native wildcard, not an old inventory.
- The declared C++ input model is a reviewed assumption, not proof that arbitrary
  Bazel code is hermetic. Undeclared file/network/runtime dependencies can invalidate
  that model. Do not enable omissions for a profile with such unresolved behavior.

On PRs, `force-full: 'true'` bypasses map reconstruction/selection and invokes the
independent full native execution path. Inputs `path` and `config` change the
checkout/config locations. The summary outputs `mode`, `status`, and
`selected-tests` (Bazel targets, not individual cases). Native reports and plans
are retained for seven days. Missing/invalid reports are never labelled passed.

## Verification and rollout

1. Review the selected native profile and its existing full command. Set up
   read-only GitHub permissions, a clean head checkout, and protected base-owned
   configuration. Preserve native cache settings; never disable caching to claim
   a Smart CI speedup.
2. First verify the approved branch push: full tests and query pass, the summary
   reports full enrollment, and `smartci-native-map-<attempt>` contains
   `enrollment/collection.json`, its bundle and `publication.json`. A failed
   install can run the independent full command but must not publish a map.
3. Run a normal source-only PR with an independent unchanged full control on the
   same source/environment. In the Action log, verify the pinned release was
   installed, then inspect map status and full/subset execution. Download
   `smartci-native-<job>-<attempt>` from the workflow artifacts.
4. Inspect `native-pr/lifecycle.json`, `execution/plan.json`, and
   `execution/execution.json`. Confirm exact base/head, map admission,
   fallback reasons, selected targets, retained build-only scope and complete
   reconciled native events. Compare failures with the independent control.
5. Check a real regression and a build/configuration change. The regression
   must remain red; unsupported changes must run the independent full suite,
   including any new tests. Missing maps must rebuild or run full, not skip.
6. Measure event-to-result and job duration including checkout, installation,
   map fetch, planning, native execution, validation and artifact upload.
   Include enrollment separately, record runner CPU differences, and retain
   negative results. Fewer selected targets alone is not success.

For maintainers: `uv sync --frozen`, `make check`, and `uv build` verify code,
contracts, typing, formatting and regression tests. Hosted safety checks also
install the native TypeScript toolchain; local skips are not a hosted pass.
Release artifacts are taken from the successful hosted safety run for the exact
release commit, then pinned by digest. No source merge is required to test a
prerelease Action SHA. Production adoption still requires the customer's review.

## Evidence status

The [hosted release gate](https://github.com/SharmaKunal14/smart-ci/actions/runs/45949086653) passed all 1,121 tests, linting, strict typing and the reproducible wheel digest check. [CLI 0.2.0a1](https://github.com/SharmaKunal14/smart-ci/releases/tag/cli-v0.2.0a1) is a published prerelease, built from commit `b2160a7e5c3571dc9bcc1ec7fdd34ad886a2e542`. Both real consumer pairs are verified below; the regression PRs remain intentionally red.
Prior CLI-based cold Abseil comparisons selected 2/252 test targets and retained
324 build-only targets, with 626/413 and 724/497 seconds native/Smart CI. Prior
warm-cache comparisons were slower with Smart CI: 198/209 and 289/307 seconds.
These are limited historical cases with differing runner CPUs, not a universal
savings claim. See [the prior execution evidence](bazel-execution.md) and
[warm-cache results](native-cache-evaluation.md).


### Passing PR delivery comparison

[Native PR #28](https://github.com/SharmaKunal14/abseil-cpp/pull/28) and
[Action PR #29](https://github.com/SharmaKunal14/abseil-cpp/pull/29) use the same
head commit `fdeb7e837cf0e8766880618312fc3bc8feed9e70`. They replay a historical
one-line hinted node insertion fix, changing `.first` to `.position`. Native
commands, test sources, flags, pinned image and resource safeguards are unchanged.
Policy and workflows are already present on the reviewed base.

| GitHub measurement | Native full | Smart CI Action |
| --- | ---: | ---: |
| Workflow creation to terminal completion | 897 s | 509 s |
| Runner job duration | 895 s | 506 s |
| Native command | 883.01 s | 484.83 s |
| Test targets with passing results | 252 | 2 |
| Native build target/configuration pairs | 576 | 326 |
| Required build-only targets retained | 324 | 324 |
| Native actions executed | 2,988 | 1,092 |

[Full run 45949727498](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45949727498)
and [Action run 45949727018](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45949727018)
both passed. The Action retrieved the authenticated producer map without rebuilding
and used no fallback. It selected `//absl/container:linked_hash_map_test` and
`//absl/container:linked_hash_set_test`. Strict post-run reconciliation checked
complete native events, the exact options/target patterns, matching selected
outcomes and all retained native build configurations.

Observed total saving: **388 seconds (43.3%)**. The Action's base-control staging,
release installation, map retrieval/validation and lifecycle/planning took 11.57
seconds before native execution. The selector's 0.657-second timer is only part
of that overhead. Queue, checkout, runner preparation, native validation, summary,
upload and cleanup are included in the workflow total.

The full runner had an AMD EPYC 9V74 and the selected runner an AMD EPYC 7763;
both exposed four CPUs. Native work decreased, but hardware and scheduling prevent
attributing the exact 43.3% to selection alone. This is one cold localized case,
not a representative average or a warm-cache saving. Counts are Bazel targets,
not individual test cases. A passing pair contains no failures with which to
estimate failure-detection recall; the separate regression check addresses one
known failure only.

An initial harness YAML error (unquoted colons in workflow names) produced six
failed startup records with zero runner jobs. Those are setup failures, not
performance samples. The corrected passing pair was triggered by a PR synchronize
event. Timing uses GitHub `run.created_at` to terminal `run.updated_at`, not the
original PR creation before that correction. No slow native attempts were dropped.


### Regression preservation through the Action

[Full control PR #31](https://github.com/SharmaKunal14/abseil-cpp/pull/31) and
[Action PR #30](https://github.com/SharmaKunal14/abseil-cpp/pull/30) share head
`1e83166d70a8ac0d99f60f743bf13f07a3cacb5c`. They restore the historical `.first`
compiler error on the passing base, without changing tests.

| GitHub measurement | Native full | Smart CI Action |
| --- | ---: | ---: |
| Workflow creation to terminal completion | 903 s | 326 s |
| Runner job duration | 899 s | 322 s |
| Native command | 888.38 s | 287.39 s |
| Passed test targets | 250 | 0 |
| Test targets that failed compilation | 2 | 2 |
| Build target/configuration pairs | 576 | 326 |
| Required build-only targets retained | 324 | 324 |
| Native actions executed | 2,982 | 1,086 |

[Native run 45951340615](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45951340615)
and [Action run 45950973426](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45950973426)
are both **failed**, correctly. Both logs identify `no member named 'first'` at
`raw_linked_hash_set.h:457:36` for `linked_hash_map_test` and `linked_hash_set_test`.
The selected test executables did not run: both failed compilation first. The full
control continued with 250 unaffected passing test targets. The Action propagated
exit code 1 and recorded no integration error or fallback.

Strict reconciliation of complete build events, native options, executed target
patterns and configuration scope found the same failed target sets and **zero
missed observed failures**. Both arms restored their runner policies. Observed
failure feedback improved by 577 seconds (63.9%). This is separate from passing
workload savings. The full host was an AMD EPYC 9V74; the selected host an Intel
Xeon 6975P-C. The hardware difference again prevents a precise causal percentage.

The [machine-readable evidence](../benchmarks/native-action-alpha-2026-11-27.json)
contains all four run/PR links, source revisions, native scope, failures, action
counts, step timings, CPU models, artifact hashes and the initial setup failures.
The existing enrollment cost is separate. All four PRs and the implementation PR
remain unmerged. No model calls or AWS deployment occurred.

The narrow milestone is successful: customers can invoke this supported native
profile through the Action, and this cold passing case was faster end to end.
It does not establish universal compatibility, a production recall guarantee,
or benefit when native caching already avoids the same work. Keep the earlier
warm-cache losses visible when deciding whether to adopt this profile.


### Automatic enrollment and next-PR reuse (CLI 0.2.0a2)

[Smart CI PR #32](https://github.com/SharmaKunal14/smart-ci/pull/32) adds automatic
map enrollment to the same Action. The pilot configuration is now eight lines:
profile plus the approved map branch/workflow. No manually assembled publisher,
workflow hash, run ID or capture command contract is supplied by the consumer.
The example above uses the tested Action commit
`e780aeb00eb5b81c35b062c65734067c03279754` and checksum-pinned CLI 0.2.0a2.

[Enrollment run 45956839926](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45956839926)
on base `182a1c5b29fe32daf2549e0507866f7bb9ae3ebc` passed all 252 native test
targets, retained 324 build-only targets and published a validated map. Its total
workflow time was 671 seconds (668 runner-job seconds): 637.79 seconds in the
native full command and 8.73 seconds in the dependency query. This was a fresh
capture, not reuse of the earlier experiment's manually configured publisher.

The next eligible source-only [Smart CI PR #33](https://github.com/SharmaKunal14/abseil-cpp/pull/33)
and [full-control PR #32](https://github.com/SharmaKunal14/abseil-cpp/pull/32)
share head `cccc702e657422a0dad864752bb103a2b188a782`. The change names the hinted
node insertion result before returning its iterator. It is a behavior-preserving
refactor; test sources, native command/flags, cache behavior and environment profile
are unchanged. These are first attempts on real PR creation events.

| GitHub measurement | Unchanged native full | Smart CI Action |
| --- | ---: | ---: |
| PR creation to completed result | 986 s | 322 s |
| Workflow creation to completion | 983 s | 318 s |
| Runner job duration | 980 s | 314 s |
| Native command | 968.98 s | 285.43 s |
| Test targets actually passed | 252 | 2 |
| Build target/configuration pairs | 576 | 326 |
| Required build-only targets retained | 324 | 324 |
| Native actions executed | 2,988 | 1,092 |

[Full run 45956992612](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45956992612)
and [Action run 45958435002](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45958435002)
both passed. Smart CI authenticated the map from the fresh enrollment run, used
no reconstruction or fallback, and selected the existing `linked_hash_map_test`
and `linked_hash_set_test` targets. Strict reconciliation verified complete native
events, exact options/patterns, matching selected outcomes and every required
build configuration. There were no observed full-suite failures to miss; this
passing case cannot estimate failure-detection recall. The earlier alpha's known
compiler-regression comparison above remains separate evidence.

Observed PR feedback improved by **664 seconds (67.3%)**. Before native execution,
Action staging took 0.79 seconds, release installation 5.84, authenticated map
retrieval/validation 4.93, and lifecycle/planning 1.34: **12.90 seconds total**.
The selector-only timing is not the total Smart CI overhead. Setup, downloads,
validation, upload and cleanup remain included in the completed GitHub timings.

**No net compute saving was observed for one additional enrollment plus one PR.**
Their combined runner time was 668 + 314 = **982 seconds**, versus **980 seconds**
for one native PR. Faster feedback is real in this pair, but total runner usage
is effectively unchanged when enrollment is extra. Two identical-saving PRs
sharing one enrollment would cross the arithmetic break-even point; that is a
calculation, not an observed multi-PR campaign. Each approved branch push currently
performs fresh enrollment. If it replaces an existing full push job, only the
additional work is incremental; that alternative was not measured here.

The full runner was an Intel Xeon Platinum 8370C; enrollment and the selected
runner used Intel Xeon 6975P-C hosts. All exposed four CPUs. Reduced native action
count establishes less work, but hardware differences confound the exact causal
percentage. This is one cold localized case, not a representative enterprise
average, arbitrary-repository support or a warm-cache improvement. Prior warm
results remain negative. All PRs remain unmerged; no AWS work or model calls.

The [machine-readable enrollment and comparison record](../benchmarks/native-action-enrollment-2026-11-27.json)
contains exact revisions, map provenance, artifact hashes, step durations, selected
scope and the separate enrollment accounting. To verify the product flow, inspect
`smartci-native-map-1` on enrollment, then `map/fetch.json`,
`native-pr/lifecycle.json`, `native-pr/execution/plan.json` and `execution.json`
in PR #33's `smartci-native-test-1` artifact. The fetched run and manifest must
match enrollment; the lifecycle must say `retrieved` with no rebuild. Uploaded
artifacts are retained for seven days; the committed result record
preserves the measurement and provenance.
