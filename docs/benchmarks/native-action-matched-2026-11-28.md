# Same-VM GitHub comparison: native caching leaves little work to avoid

The completed controlled comparison **does not demonstrate a reliable Smart CI
speed benefit on this warm Abseil profile**. Three of four paired arm intervals
were slower; one was 1.0 second faster. Median paired slowdown was **9.9 seconds**.
All four runs passed and all attempts are included, without reruns or exclusions.
The predeclared success criterion was not met.

The [predeclared campaign](native-action-matched-campaign.md) used the unchanged
published Action `e780aeb00eb5b81c35b062c65734067c03279754` and CLI `0.2.0a2`.
[Smart CI PR #34](https://github.com/SharmaKunal14/smart-ci/pull/34) adds the
measurement harness and its safety tests; it does not change the selector,
published release, native tests or native caching. The
[complete measurement record](native-action-matched-2026-11-28.json) contains
all attempts, revisions, intervals, native cache evidence and artifact hashes.

## Controlled GitHub results

| Pair / real PR | Order | Full arm | Smart arm | Smart difference | Whole joint PR |
| --- | --- | ---: | ---: | ---: | ---: |
| [1 / #40](https://github.com/SharmaKunal14/abseil-cpp/pull/40) ([run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/46002042899)) | Full → Smart | 48.1 s | 50.9 s | 2.9 s slower | 264 s |
| [2 / #41](https://github.com/SharmaKunal14/abseil-cpp/pull/41) ([run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/46002744991)) | Smart → Full | 40.4 s | 57.3 s | 17.0 s slower | 263 s |
| [3 / #42](https://github.com/SharmaKunal14/abseil-cpp/pull/42) ([run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/46003462420)) | Smart → Full | 42.4 s | 60.9 s | 18.5 s slower | 267 s |
| [4 / #43](https://github.com/SharmaKunal14/abseil-cpp/pull/43) ([run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/46004198460)) | Full → Smart | 67.5 s | 66.5 s | 1.0 s faster | 404 s |

The full/Smart columns are **observed per-arm intervals inside real GitHub PR
jobs**, including independent cache restore and fingerprint verification,
preparation, execution and audit upload. Full and Smart run sequentially on the
same VM. The last column is the **actual whole joint PR-to-result time** including
queue, shared setup, both arms, reporting and cleanup. It is not the latency of
a standalone Smart CI PR. Adding the same shared cost to each arm yields an
accounting estimate, not two independently observed standalone PR lifecycles.

Full-arm median/range: **45.2 s / 40.4–67.5 s**. Smart-arm median/range:
**59.1 s / 50.9–66.5 s**. Median paired saving is **−9.9 s**, ranging from
an 18.5-second loss to a 1.0-second gain. The paired median differs from subtracting
the two arm medians. Aggregate arm time is 198.3 s full versus 235.6 s Smart:
**37.3 additional seconds** across the four repetitions.

The gate required a positive paired median, at least three of four faster pairs,
and gains in both order groups. It failed. Full-first pair differences were
−2.9 and +1.0 seconds; Smart-first differences were −17.0 and −18.5 seconds.
The order effect matters: the first arm's filesystem-cache reset/flush took
6–10 seconds versus 2–3 seconds for the second arm. Balance limits this bias but
does not eliminate all carry-over. A **post-hoc sensitivity calculation**, removing
only the rounded reset-step cost, leaves losses of 7.9, 10.0, 12.5 and 3.0 seconds.
That calculation does not remove memory-state effects and is not a measured
production run without the reset. The primary result above is unchanged.

## Matched inputs and remaining limits

Every PR has base `4b3a73d04b03e502be99cb35835b472dfa85b814` and head
`77812711d4c052489b8bbd03eba7a50882f7b491`. The only source change names the
existing hinted-node insertion result before returning its iterator in
`absl/container/internal/raw_linked_hash_set.h`. Existing tests are unchanged.
This is one small passing refactor, not a representative distribution of changes.

Both arms use the same upstream GCC/C++17 command/profile and digest-pinned
compiler image. Pulling the image happens once before either arm and remains
part of the measured joint job. Each native invocation starts a fresh container,
tmpfs workspace and Bazel server. Before each arm, the exact same approved base
cache is independently downloaded and its complete content fingerprint checked.
The used cache is moved out of the active path before the next restore. No
PR-head output is reused by the other arm; PR cache permissions are read-only.

The **native disk cache is warm; filesystem memory caches are reset** before each
main invocation. The reset is applied to both arms and counted in their times.
It limits order carry-over but is a benchmark-only control, not a production
recommendation. A normal cache restore may leave file pages warm, so these results
must not be presented as identical to every ordinary production cache state.
The Action's installation/planning runs after its reset and counts naturally.
CPU scheduling, frequency and other temporal VM noise remain possible. Four
repetitions do not establish a population-wide effect or confidence interval.

Within each pair, both arms share the same recorded VM boot identity and four
visible CPUs. Pairs 1–3 used Intel Xeon 6975P-C; pair 4 used AMD EPYC 7763.
Hardware is matched **within** each comparison, not asserted identical across
all four hosts. Shared image loading took 136, 141, 137 and 250 seconds; all of it
is included in the joint PR and runner totals. The small fourth arm gain is below
the two-second whole job-setup bound for unallocated Action acquisition.

GitHub acquires referenced Action repositories during initial job setup, outside
the arm timer. Some acquisition and post-Action cleanup is Smart-only. We retain
those times in the joint cost and bound acquisition conservatively by the whole
job-setup step. Additional Smart-only costs cannot turn an observed arm loss
into a gain. The JSON's single-arm accounting fields charge identical shared
costs and are not an exact allocation of standalone product overhead.

## Actual native work and outcome parity

| Verified evidence in every pair | Full control | Smart CI |
| --- | ---: | ---: |
| Test targets with passing outcomes | 252 | 2 |
| Uncached test runs | 2 | 2 |
| Cached test runs | 363 | 0 |
| Local native actions | 8 | 8 |
| Disk-cache action hits | 1,655 | 781 |
| Required build-only targets retained | 324 | 324 |

Both rerun `//absl/container:linked_hash_map_test` and
`//absl/container:linked_hash_set_test`. These are native target/run counts,
not individual C++ test-case counts. Smart CI omits 250 test targets, but native
caching already avoids executing those tests. The measurable opportunity is
therefore reduced analysis/cached-output handling, not avoiding additional local
build or test actions.

All four plans were byte-identical, selected 2/252 targets, retrieved the same
authenticated exact-base map and required no fallback or reconstruction. Native
event reconciliation verifies options, target/configuration scope, all 324
build-only targets and exact matching selected outcomes. Both approaches pass.
There are **zero missed observed failures and zero full-control failures**;
failure-detection recall cannot be estimated. This campaign does not replace
behavioral-regression, compiler-regression or broad-change fallback verification.
Prior regression/fallback evidence remains separate; no new safety guarantee is
claimed from these passing repetitions.

## Where the time went

| Pair | Native command: full / Smart | Smart setup before execution | Selector alone |
| --- | ---: | ---: | ---: |
| 1 | 32.95 / 28.15 s | 12.30 s | 0.39 s |
| 2 | 34.22 / 31.18 s | 11.57 s | 0.45 s |
| 3 | 32.71 / 30.63 s | 13.44 s | 0.41 s |
| 4 | 56.03 / 46.15 s | 10.63 s | 0.64 s |

The native command saves **2.1–9.9 seconds**. Before it can execute, the Action
spends **10.6–13.4 seconds** setting up Python, staging trusted control files,
installing the pinned CLI and retrieving/preparing the map. The selector itself
costs only **0.39–0.64 seconds**. Execution validation, summaries and uploads add
more work. These are nested portions of the measured totals, not additional
amounts to add again. Optimizing graph traversal alone cannot explain or recover
most of this overhead.

The earlier [separate-job warm comparison](native-action-warm-2026-11-27.md)
had two large apparent gains dominated by CPU/common-setup differences. This
controlled result gives no support for treating those gains as attributable
product savings. Earlier cold-profile benefits remain separate evidence; they do
not establish value when native caching already avoids the same expensive work.

## Compute, cache and lifecycle cost

The fresh [seed run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/46000242013)
took **692 s workflow / 689 s runner time**, including a 644.31-second native
full command and an 8.53-second dependency query. It passed all 252 test targets,
retained 324 build-only targets and published the exact-base map and native cache.

The four joint comparison jobs used **1,172 runner-seconds**. Including enrollment,
the actual five-job benchmark consumed **1,861 runner-seconds (31m01s)**.
The initial harness safety check used another **168 seconds**, bringing benchmark
plus initial development verification to **2,029 seconds (33m49s)**. The later
report-publication check is separate development work and is reported on PR #34;
it is not silently charged as customer CI or a saving. Actual whole joint
PR-to-result times were 264, 263, 267 and 404 seconds. Their median is 265.5 seconds.
These jobs intentionally execute both approaches; aggregate experiment compute
is different from one developer's potential feedback latency.

A native warm-cache pipeline also needs its cache seed. Charging the whole combined
seed only to Smart CI overcharges shared native work, while treating enrollment
as free hides query, installation and map publication. There is no matched
native-only seed here, so the exact incremental enrollment cost is unmeasured.
The base remained fixed: no evolving-base refresh or observed lifecycle
amortization claim follows. Broader scenarios and a second repository remain
deferred because this warm-profile performance gate did not pass.

The single cache contained **858,057,215 raw bytes / 112,970,857 compressed bytes**.
Eight independent restores imply 903,766,856 nominal compressed payload bytes,
plus the seed upload. Four map downloads add 1,414,912 nominal compressed bytes.
Benchmark artifacts total **3,145,150 bytes**, retained seven days. These are
metadata payload sizes, not measured wire traffic or a dollar bill; container
transfer bytes were not metered. Cache ID `11202450055` was deleted only after
all consumers completed, and the cache listing is empty. The immediate aggregate
storage-usage counter lagged the deletion; a follow-up read confirmed zero
entries and zero bytes. Both observations are preserved in the JSON. No paid
storage limits or runner settings were increased.

## Verification and changed files

1. Open each linked PR and run. Confirm its exact head/base, one `compare` job,
   and the declared execution order. All PRs remain open and unmerged.
2. Download `matched-comparison-1`, `matched-native-full-1` and
   `smartci-native-compare-1`. In the comparison artifact, inspect `context.json`,
   `comparison.json`, both `cache-verified.json` files and
   `native-preparation.json`. The VM boot hashes and independently restored
   cache receipts must match. Compare recorded monotonic arm intervals with job
   and PR timestamps; do not substitute native-command duration for total cost.
3. Inspect Smart CI's `plan.json`, `lifecycle.json`, `map/fetch.json` and both
   arms' `execution.json` / `native.bep.json`. Confirm the selected targets,
   all retained build-only configurations, actual disk-cache hits, the two
   uncached runs and exact native outcome parity. Full execution retains its
   native wildcard and existing cache behavior.
4. The committed JSON preserves all measurement values and artifact digests
   after the seven-day artifact retention expires. The producer run and cache
   receipt identify which exact base evidence each arm used.

Changed implementation files are `examples/abseil/matched_trial.py`,
`action-matched-workflow.yml`, `action-matched-enroll-workflow.yml`,
`action-matched-policy.json`, `action-matched-cache-publisher.json` in that
directory, and `tests/test_matched_trial.py`. Documentation changes are this
report/JSON, the campaign predeclaration, README, plan and Action onboarding guide.
The helper rejects undeclared branches, reused head caches, wrong cache receipts,
different VM identities and invalid ordering/intervals; either native failure
still fails the combined job. It is a bounded measurement helper, not a new
selection engine. Base-owned control files and read-only PR credentials remain
in force. Genuine missing/invalid evidence retains reconstruction/full fallback.

[Hosted harness verification](https://github.com/SharmaKunal14/smart-ci/actions/runs/46000196502)
passed **1,179 tests**, formatting, lint, strict typing and checksum-verified
package build. Report-publication checks are linked separately from PR #34;
they are development verification, not customer benchmark work. No merges,
AWS deployments, paid model calls or paid runner/storage-limit increases were
made. Model campaign gates remain disabled.
