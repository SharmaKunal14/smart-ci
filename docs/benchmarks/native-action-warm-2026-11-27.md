# Published Action with a working native cache: mixed latency results

The bounded first gate completed on GitHub: one enrollment and three fresh PR
pairs, with no reruns or discarded attempts. Smart CI was faster in two pairs
and slower in one. **This does not yet establish an attributable warm-cache
benefit.** CPU models differed in every pair, and the largest timing differences
occurred in common native setup, outside Bazel's build/test interval.

The [predeclaration](native-action-warm-campaign.md) was published before these
runs. [Smart CI PR #33](https://github.com/SharmaKunal14/smart-ci/pull/33) adds the
evaluation configuration and safety tests; it does not change the published
Action, CLI, selector or native tests. The
[complete measurement record](native-action-warm-2026-11-27.json) retains every
run, revision, timing, CPU, cache receipt, map provenance and artifact hash.

## Actual end-to-end results

Times run from PR creation to terminal workflow completion, including queue,
checkouts, cache transfer/validation, CLI installation, map retrieval, planning,
native execution, reports, uploads and cleanup. Every run passed.

| Pair | Native full PR / run | Smart CI PR / run | Full | Smart CI | Observed Smart CI difference |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | [#34](https://github.com/SharmaKunal14/abseil-cpp/pull/34) / [45964263873](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45964263873) | [#35](https://github.com/SharmaKunal14/abseil-cpp/pull/35) / [45964273005](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45964273005) | 313 s | 389 s | 76 s slower |
| 2 | [#37](https://github.com/SharmaKunal14/abseil-cpp/pull/37) / [45965212482](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45965212482) | [#36](https://github.com/SharmaKunal14/abseil-cpp/pull/36) / [45965202455](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45965202455) | 329 s | 223 s | 106 s faster |
| 3 | [#38](https://github.com/SharmaKunal14/abseil-cpp/pull/38) / [45966174238](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45966174238) | [#39](https://github.com/SharmaKunal14/abseil-cpp/pull/39) / [45966190588](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45966190588) | 312 s | 226 s | 86 s faster |

Native median/range: **313 s / 312–329 s**. Smart CI median/range:
**226 s / 223–389 s**. The median *paired* saving is **86 s**, ranging from a
76-second loss to a 106-second gain. The difference between the separate arm
medians is 87 seconds; that is a different statistic. Three samples do not support
a precise causal percentage or a representative enterprise average.

## Equal inputs and actual cache reuse

All six PRs have base `dd9e295fe9855126bc792f4ab1be5dd81035f23f` and head
`243d1376b3ca4a54c64c25b00ea3a8ae33129907`. The source change names an existing
hinted-node insertion result before returning its iterator. It is the same
behavior-preserving change used in the earlier cold Action comparison. Test
sources, the upstream GCC/C++17 fastbuild command, flags, pinned container,
native caching and resource safeguards were preserved. Full control already
benefits from Bazel's native reuse; cached tests were not forced to rerun.

Both arms independently restored the exact same trusted base-only disk cache.
Publisher, base revision, workflow digest, tool/profile identity and cache content
were validated. PRs had read-only cache permission and could not publish head
results. No arm benefited from another PR's work. Smart CI used the unchanged
published Action `e780aeb00eb5b81c35b062c65734067c03279754` / `cli-v0.2.0a2`.

All six were valid **warm native build/test-cache** samples. The container image
was cold on fresh hosted runners in both arms. “Warm” does not mean all setup
layers were cached. No cache-miss, setup-error or retry sample was excluded.

| Verified native evidence, in every pair | Full control | Smart CI |
| --- | ---: | ---: |
| Test targets with outcomes | 252 | 2 |
| Uncached test runs | 2 | 2 |
| Cached test runs | 363 | 0 |
| Local native actions | 8 | 8 |
| Disk-cache action hits | 1,655 | 781 |
| Required build-only targets retained | 324 | 324 |

The two uncached targets were `linked_hash_map_test` and `linked_hash_set_test`
in both arms. Bazel runs and targets are not individual C++ test-case counts.
Smart CI omitted 250 targets, but native caching had already avoided executing
their tests. Smart CI reduced analysis and cached-output work; it did not avoid
additional local compilation/test actions in this case.

All three plans were byte-identical, reused the validated map, and had no
reconstruction or fallback. Native event graphs, options, configurations, selected
outcomes and preserved build scope reconciled. **Zero observed failures were
missed, but there were zero full-control failures: recall is not estimable.**
These passing repetitions do not replace behavioral-regression verification.

## Where the time went

| Pair | CPU model, full / Smart | Bazel interval, full / Smart | Native command outside Bazel, full / Smart | Smart preparation before native command |
| --- | --- | ---: | ---: | ---: |
| 1 | AMD EPYC 7763 / AMD EPYC 9V74 | 45.10 / 32.84 s | 243.88 / 313.54 s | 12.62 s |
| 2 | AMD EPYC 9V74 / Intel Xeon 6975P-C | 35.58 / 26.76 s | 272.51 / 145.09 s | 14.08 s |
| 3 | AMD EPYC 7763 / Intel Xeon 6975P-C | 46.27 / 29.17 s | 243.73 / 147.79 s | 12.70 s |

All runners exposed four CPUs on `ubuntu-24.04`, but processor models differed.
Bazel intervals come from native start/finish events. Residual native command
time includes container acquisition/startup and process overhead; it is not a
direct measurement of image transfer alone. The first full-control log explicitly
records about 238 seconds pulling the pinned image.

Large positive differences in pairs 2/3 are dominated by common setup, not the
small difference inside Bazel. Selector timing was only 0.42–0.48 seconds;
staging, CLI installation, authenticated map retrieval and lifecycle preparation
together cost 12.62–14.08 seconds. Other job overhead remains in the total.
CPU and network/setup variation prevent assigning observed savings precisely to
Smart CI. Earlier warm CLI losses, **198/209 s** and **289/307 s**, remain in
[the prior record](../onboarding/native-cache-evaluation.md).

## Enrollment, aggregate compute and storage

[Seed run 45962439328](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45962439328)
took **790 s workflow / 788 s runner time**. It passed all 252 native targets,
retained 324 build-only targets, and published both map and cache. Its native
full command took 741.24 seconds; the Smart CI query took 12.28 seconds.

The three native PR jobs used **935 runner-seconds**; Smart CI used **817**.
Their observed difference was 118 seconds, subject to the same setup confounding.
The actual seven-job benchmark consumed **2,540 runner-seconds (42m20s)** including
enrollment. The initial evaluation-code safety job took another **168 seconds**,
separate from customer lifecycle work.

A warm native pipeline also needs its cache seed. Charging the entire 788-second
combined seed only to Smart CI overcharges that shared work; treating it as free
hides the additional query, installation and map-publication work. No matched
native-only seed was run, so exact incremental enrollment cost is not measured.
An intentionally conservative all-extra-seed view is 1,605 Smart versus 935 native
runner-seconds, **not a fair measured net saving**. No observed lifecycle
break-even or amortization claim follows. The base stayed fixed; refresh costs
across changing base commits have not been measured here.

The single cache held **858,009,698 raw bytes / 113,035,107 compressed bytes**.
Six restores imply 678,210,642 nominal compressed payload bytes, plus the seed
upload. Three map retrievals added 1,062,444 nominal compressed bytes. Benchmark
artifacts total 2,989,298 bytes, retained seven days. These are metadata payload
sizes, not measured wire traffic or billing; container-transfer bytes were not
metered. Cache ID `11191617890` was deleted after all consumers completed, and
GitHub reported zero remaining cache entries. No paid runner/storage settings
were increased.

## Decision and verification

The numeric latency screen passed: positive median saving and two faster pairs.
Evidence remains **inconclusive about a useful attributable operating range**:
common setup dominates the gains and native uncached work is unchanged. Do not
turn the faster median into a product speedup claim. Keep broader cases,
evolving-base lifecycle and second-repository validation deferred while this
measurement limitation remains unresolved. This completes the bounded first
gate, not the full requested evaluation matrix.

No behavioral-regression, shared-change, test-only or broad-fallback case was run
in this new campaign. Earlier compiler/fallback evidence remains separate. The
next evaluation needs comparable setup/CPU conditions while still counting their
full lifecycle cost; warming or excluding setup only for Smart CI is invalid.

To inspect the results:

1. Open a linked full/Smart PR pair and completed workflow. All PRs remain open
   and unmerged. Compare PR creation against terminal workflow timestamps;
   inspect job/step times separately from native command time.
2. Download `independent-native-1` from full control and `smartci-native-test-1`
   plus `warm-cache-1` from Smart CI. Check `cache-admission.json`, identical
   receipts/identities, `execution.json`, and `native.bep.json`.
3. Inspect Smart CI's `plan.json` (two selected targets), `lifecycle.json`
   (`retrieved`, no rebuild) and `map/fetch.json` (seed run above). Compare exact
   selected outcomes with full control. Inspect native cached/uncached run counts
   rather than treating 252 outcomes as 252 reruns.
4. Use the committed JSON for revisions, hashes, all attempt timings, CPU models
   and cache provenance after the seven-day artifact retention ends.

[Hosted safety checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/45962363196)
passed 1,167 tests, formatting, lint, types and the checksum-verified package
build. No selector safety rules were weakened. All model campaigns remained
disabled; no paid model calls, merges or AWS deployments occurred.
