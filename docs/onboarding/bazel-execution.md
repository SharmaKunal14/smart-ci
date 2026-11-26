# Executing native PR plans

`smartci bazel execute` derives a plan from authenticated native evidence and
executes a reviewed full or subset command. It does not accept an externally
supplied selection. The existing source-change eligibility rules remain in force:
only supported edits to existing declared C++ source inputs can authorize omissions.
Changed build definitions, unknown inputs, invalid evidence and unproven impact
retain the independent full wildcard command.

```sh
smartci bazel execute \
  --repo "$REPOSITORY_ROOT" --base "$PR_BASE" --head "$PR_HEAD" \
  --config "$TRUSTED_EXECUTION_CONFIG" \
  --bundle "$AUTHENTICATED_BUNDLE" --expected-digest "$MANIFEST_DIGEST" \
  --output "$NEW_EXTERNAL_OUTPUT"
```

Omit both map arguments to run full, or use `--force-full` for explicit rollback.
`--must-run` preserves configured mandatory targets. A wrong or dirty checkout
fails before running commands; it is not a successful full-suite check of the PR.

Export the configuration contract with `smartci schema bazel-execution`. It binds
the native profile, full/subset argument arrays and timeouts, and the exact subset
Bazel options digest. The latter differs from full only because the reviewed
adapter uses a target-pattern file. The executor writes `capture/targets.txt`;
commands write `capture/native.bep.json`. Only literal `{repo}` and `{capture}`
arguments are substituted. No shell or inherited model/GitHub credentials are used.
Configuration must come from the reviewed CI control plane, never from the PR.

Before and after execution the actual Git checkout must match the requested
commit. The native event stream must be complete and match the toolchain, options,
working directory relationship, planned target patterns and process exit code.
A subset must report exactly the selected tests and every retained build-only
configuration. Compilation failures can explain only their own unexecuted tests;
they still fail CI. Flaky, missing, contradictory or malformed evidence cannot
produce success. A full fallback can legitimately discover new targets and is not
forced to match an old inventory.

The new Abseil adapter preserves the reviewed native script, compiler, container,
workers and test flags. It changes only the wildcard to a target-pattern file for
subsets, retains bounded logs and cleans its uniquely named container. Core
execution uses bounded process groups; filesystem isolation still belongs to CI.
An environment filter alone is not a sandbox. Use disposable runners without
persisted credentials. These controls are not a guarantee of perfect dependency
knowledge or a defense against arbitrary malicious build code forging evidence.

## GitHub integration

`examples/abseil/pr-workflow.yml` demonstrates a bounded, isolated pilot. A separate
token-scoped step resolves the reviewed publisher branch and calls `bazel fetch`;
there is no saved run ID or per-PR handwritten test list. Publisher policy and the
producer's exact capture configuration are pinned in the tool checkout. Execution
then validates compatibility with the actual PR base. If retrieval or compatibility
fails, `run_pr.py` checks out that base, reconstructs the map, and restores the exact
PR head. Failed reconstruction retains full execution. PR-produced maps are not
published as trusted baselines. Failed restoration stops the job.

Planner installation failure uses the standard-library native full runner. Native
test failures are not retried or turned green by a successful planner. The pilot
is capped at 60 minutes to allow a missing-map rebuild plus head execution; routine
cache hits do not run enrollment. Artifacts expire after seven days. There are no
AWS resources or model calls.

`pr-baseline-workflow.yml` runs only the independent full native suite, with the
same source/profile and crash-report safeguards. It installs no Smart CI planning
dependencies. Use separate real PRs with identical application/test/build trees,
then compare PR-event-to-workflow-completion time, total runner time, outcomes,
native build/test counts, and action counts. Initial enrollment and cache misses
must be reported separately. A smaller plan is not a measured speed improvement.

Verification covers subprocess execution, token filtering, full fallback,
new targets in full runs, exact subset/build-only scope, compiler failures, profile
drift, timeouts, dirty checkouts, lifecycle rebuilding and failed head restoration.
The [hosted safety suite](https://github.com/SharmaKunal14/smart-ci/actions/runs/45773092592)
passed 817 tests, formatting, lint, types and both package builds. The initial CI
attempt caught a missing exported schema; that file was added before the candidate
experiment, without changing runtime code.

## First real PR comparison

Both PRs replay the same historical hinted node-insertion fix: `.first` becomes
`.position` in `raw_linked_hash_set.h`. Their application, test and build trees are
identical. This is a repeated workload for the new integration, not a new scenario.

| GitHub measurement | Native PR #13 | Smart CI PR #14 |
| --- | ---: | ---: |
| PR creation to completed workflow | 626 s | 413 s |
| Runner time | 620 s | 406 s |
| Passed Bazel test targets | 252 | 2 |
| Retained build-only targets | 324 | 324 |
| Bazel actions | 2,988 | 1,092 |

[Native run 45771460665](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45771460665)
and [Smart CI run 45772824303](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45772824303)
both passed. Smart CI saved **213 seconds / 34.0% end to end** in this pair. It
retrieved the reviewed map, performed no reconstruction, selected
`linked_hash_map_test` and `linked_hash_set_test`, and had no fallback. Native
events independently confirm the selected test results and preservation of every
build-only configuration. Both runners restored their temporary crash-report policy.

The GitHub map-discovery step took 4 seconds. The execution planner reported
0.460 seconds, which excludes retrieval, prior compatibility validation, interpreter
startup and dependency installation. Those costs are included in the 413-second
whole-workflow result. Native command durations were 609.42 and 383.87 seconds;
they are not substituted for the end-to-end measurement.

Download `independent-native-1` from the native run and inspect
`native-control/execution.json`. From the Smart CI run download `automatic-native-1`
and inspect `map/fetch.json`, `native-pr/lifecycle.json`, and
`native-pr/execution/{plan,execution}.json`. The
[versioned record](../benchmarks/abseil-automatic-execution-2026-11-26.json) retains
timestamps, exact revisions, profile, source identity, artifact hashes and limits.
The control pins `cbc9544`; the candidate pins `4acbf07`. The only intervening tool
change is the exported schema; executable code is byte-identical.

This is one cold-run pair on one reviewed native profile. Runner/image-download
variation remains included, and private remote-cache behavior is unmeasured. The
661-second initial enrollment is separate and must be amortized. Target counts are
not individual test-case counts. Repeat this path and verify live regression,
shared-change and missing-map/full-fallback cases before making broader claims.
Earlier Abseil measurements remain evidence for the previous pilot harness.

## Repeat on unchanged PR code

Reopening the same PRs produced a second independent pair on fresh runners:
[native run 45775890117](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45775890117)
took **724 seconds**, and
[Smart CI run 45775903321](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45775903321)
took **497 seconds**, measured from each actual reopened event through completed
workflow. Both passed: **227 seconds / 31.4% saved**. The first pair remains
626/413 seconds; no slower attempt was discarded.

The second plan is byte-for-byte identical to the first. Independent reconciliation
of complete native build events confirms 252 versus 2 passing test targets, all
324 build-only targets and their configurations retained, and 2,988 versus 1,092
Bazel actions. Both runners restored their crash-report settings. The map was
retrieved without reconstruction. See the [repeat record](../benchmarks/abseil-automatic-repeat-2026-11-26.json)
for event timestamps, per-step durations and artifact hashes.

These two cold pairs demonstrate repeatability for one localized workload. They
do not measure private remote-cache behavior, prove arbitrary dependency
completeness, or establish failure detection: both PRs contain the passing fix.
Separate regression and missing-map cases exercise those lifecycle boundaries.

## Native regression preservation

[PR #15](https://github.com/SharmaKunal14/abseil-cpp/pull/15) and
[PR #16](https://github.com/SharmaKunal14/abseil-cpp/pull/16) have identical complete
Git trees. They restore the historical `.first` error in hinted node insertion,
without changing existing tests. Both pin tool `7be5ead` and use the same reviewed
compiler and native keep-going profile.

The [full control](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45777124415)
and [selected run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45777511387)
both **failed**, as they should. Their native logs identify the same two compilation
failures in `linked_hash_map_test` and `linked_hash_set_test`: no member named
`first`, at `raw_linked_hash_set.h:457:36`. Full execution passed 250 other test
targets. The candidate selected only those two targets; neither reached test
execution because compilation failed. It did not convert these failures to green.

Independent reconciliation verifies complete build events, identical failed-target
sets and retention of all 324 build-only targets/configurations. There are zero
unmatched native failures in this case. The map was retrieved without rebuilding.
The [record](../benchmarks/abseil-automatic-regression-2026-11-26.json) includes
source identities, diagnostic evidence, hashes and exact native scope.

PR-to-completed-workflow feedback was 1,080 seconds native and 333 seconds selected.
These are failure-feedback measurements on a keep-going profile, not passing-run
timings or a general recall estimate. Keep them separate from the two passing
comparison pairs. A small replay cannot establish that every future regression
will be caught.
