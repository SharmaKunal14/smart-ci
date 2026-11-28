# HttpClient: measured savings from avoiding uncached native work

The bounded real-GitHub experiment found a useful **candidate operating range**:
a localized Apache HttpClient REST change can omit unrelated Maven modules whose
native builds and integration tests would otherwise execute. It does not establish
repeatable production savings. The previous [warm Abseil negative result](native-action-matched-2026-11-28.md)
remains valid: Bazel already avoided the expensive work in that configuration.

Implementation: [Smart CI PR #35](https://github.com/SharmaKunal14/smart-ci/pull/35),
experimental Maven Action and hash-verified CLI
[0.2.0a4](https://github.com/SharmaKunal14/smart-ci/releases/tag/cli-v0.2.0a4).
The three HttpClient PRs and Smart CI PR remain unmerged. All performance evidence
below comes from GitHub; local tests are not performance measurements.

## What changed and why this workload differs

The native pipeline runs Maven `clean verify` across ten reactor projects. Its
cache restores dependencies, not successful test results. Native integration tests
and their Docker setup still execute. The new Action obtains the active effective
Maven models, maps changed Java paths to modules, follows consumers, includes build
prerequisites and retains all POM aggregators. It passes the resulting projects to
Maven; native goals, profiles, tests, assertions and failures are unchanged.

The REST change selected root, BOM, core HttpClient and Jakarta REST (4/10 projects).
It omitted cache, fluent, observation, SSE, testing and WebSocket modules under the
[reviewed input contract](../maven-action.md). Root license checks still ran. This
is automatic module selection, not individual Java test-method selection. Maven
already executes a supplied `--projects` list: Smart CI adds PR mapping, evidence
checks, fallback and audit. It has not beaten a manually supplied perfect list.

## Results and measurement boundaries

These are sequential full/Smart arms on **the same VM within each pair**, with
independently restored identical trusted base Maven caches and fresh build outputs.
Wrapper and Docker caches start cold in both arms. Do not call this a warm build
or test-result-cache comparison. Each pair uses identical source, JDKs and native
flags. CPU models differ between scenarios, so compare within pairs.

| Real PR and run | Native execution, full / Smart | Cache-to-upload interval, full / Smart | Executed cases, full / Smart | Outcome |
| --- | ---: | ---: | ---: | --- |
| [#1 maintenance](https://github.com/SharmaKunal14/httpcomponents-client/pull/1), [run](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46122180914) | 262.1 / 59.0 s | 267 / 75 s | 3,165 / 1,331 | Both pass; subset, no fallback |
| [#2 historical regression](https://github.com/SharmaKunal14/httpcomponents-client/pull/2), [run](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46122960501) | 224.0 / 50.5 s | 228 / 67 s | 3,165 / 1,331 | Both fail the same one existing test; subset |
| [#3 POM comment](https://github.com/SharmaKunal14/httpcomponents-client/pull/3), [run](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46123082526) | 226.3 / 224.0 s | 234 / 240 s | 3,165 / 3,165 | Both pass; full fallback |

The cache-to-upload interval includes cache transfer/validation, native builds and
tests, CLI installation, planning, Action setup and arm artifact upload; Smart
post-action time is added (one second for #1). It **excludes shared job setup and
benchmark-only prepare/finish**. It is not measured standalone PR feedback latency.
Smart planning took 3.604 s, 4.099 s and 0.036 s respectively. The POM change bypassed
model collection and recorded `GLOBAL_OR_UNSUPPORTED_CHANGE`.

The subset interval reductions were 192 s (71.9%) and 161 s (70.6%). They accompany
actual removal of native work, unlike the warm Abseil trial. They are observations
from two different scenarios, not a repeated-scenario median or causal estimate
of every saved second. The full fallback added six seconds in this interval;
there was no avoided work and no useful selection benefit.

All 3,183 full-suite testcase outcomes were reconciled independently from 325
native XML reports: 3,165 actually executed and 18 native skips. The subset had
1,331 executed cases from 166 XML reports, no skips. XML report counts are not
source-test-file counts. All shared case outcomes matched; zero observed full
failures were missed. The regression is the historical trailing-slash REST bug
fixed upstream in `430191f96012a73cc4fb6b089b32838f07e423ce`. Only implementation
changed. Both commands returned 1 and the same existing case failed:

```text
RestClientIntegrationTest.getBook_withTrailingSlashBaseUri_doesNotProduceDoubleSlash
jakarta.ws.rs.client.ResponseProcessingException: REST response processing error
```

The regression comparison is green because it verified that expected failure;
the defective code did not pass its tests. One detected regression does not
establish universal recall. The passing pair alone provides no recall evidence.

## Every attempt, complete workflow time and confounders

| Attempt | Order | Full / Smart raw arm interval | Complete paired workflow | Runner job | Result |
| --- | --- | ---: | ---: | ---: | --- |
| [1](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46120604265) | Full first | Neither executed | 26 s | 23 s | Bootstrap import failed on system Python 3.12 |
| [2](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46121221251) | Full first | Incomplete | 337 s | 334 s | Full passed; candidate setup rejected an active native container |
| [3](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46122180914) | Full first | 290.6 / 76.3 s | 381 s | 378 s | Valid maintenance comparison |
| [4](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46122960501) | Smart first | 233.6 / 86.7 s | 341 s | 337 s | Valid regression comparison |
| [5](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46123082526) | Full first | 254.4 / 246.7 s | 768 s | 521 s | Valid full-fallback comparison |

Workflow time is GitHub run creation to its completed `updated_at`, including
queueing, shared checkout/JDK setup, both arms, reporting and cleanup. Attempt 5
waited 247 seconds before its job started behind the bounded concurrency gate.
**These joint workflow times are not separate full-vs-Smart PR latencies.**

Raw arm intervals include benchmark preparation and native-container settling.
Preparation/finish API durations were full/Smart **24/2 s**, **6/19 s**, **21/7 s**
for attempts 3–5. The first arm repeatedly paid more Docker cleanup/preparation;
native Ryuk cleanup also takes several seconds. Consequently, the raw fallback
arm looks 7.6 s faster despite avoiding no native work. The cache-to-upload table
separates that measurement overhead and shows the six-second loss. Shared setup,
final comparison/upload and other post-actions remain in complete job totals.

Attempt 1 was fixed by postponing Python annotations and testing the bootstrap
under the runner's system Python. CLI 0.2.0a3 is retained with a warning; 0.2.0a4
contains the correction. Attempt 2 was fixed by waiting at most 45 seconds for
native containers to settle, charging the wait to the owning arm. Persistent
containers still invalidate a comparison; no active service is forcibly erased.
Its original container identity was not recorded, so do not assert it was Ryuk.

All five allowed attempts were consumed. Only one valid passing pair remains,
so the predeclared **repeatability gate is not met**. The opposite-order regression
is useful evidence, but is not a substitute for repeated passing comparisons.

## Costs, safety assumptions and remaining work

The [native qualification/enrollment](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46118291884)
cost 253 runner-seconds (259 s workflow), including full native execution and
effective-model capture. Five paired attempts cost 1,593 runner-seconds, including
357 seconds in failed attempts. **Total native experiment: 1,846 s / 30m46s.**
Four implementation quality-check jobs cost another 701 s / 11m41s before the
final report check. These are measured runner durations, not an AWS/model bill
or production savings. Running both controls consumes extra experiment compute.

The sole cache held 182,217,417 raw bytes / 150,944,345 compressed bytes. Every
valid arm matched its file-tree digest; no PR-head cache was published. Cache
deletion and zero remaining fork caches were verified after completion. The paired
workflow is now disabled to prevent accidental extra runs; artifacts expire after
seven days. A new trial needs a fresh trusted seed and a new bounded run allowance.
No paid runner/storage settings were increased. Model campaigns remain disabled.

The Action requires a base-owned command and reviewed native-tree digest, clean
exact head, complete supported Maven models and a declared-input contract. Global
POM/configuration/resource changes, unknown paths and invalid evidence retain full
execution. Native failures propagate. The Action uses read-only permissions and
does not pass GitHub credentials to native commands; disposable runners and
non-persisted checkout credentials remain required.

The input contract is an assumption requiring review, **not a proof that Java
cannot access arbitrary files or services**. New cross-module runtime behavior
can violate it even without a POM change. Do not enable omissions for such code.
The pinned native-tree review is not a complete toolchain/environment attestation.
Native base updates invalidate it until reviewed again. Automatic evolving-base
refresh, amortization, warm Docker/build-cache behavior and representative PR
fallback frequency were not established. The deliberately selected POM-comment
case is not a dependency-upgrade test. Further product rollout is not justified
by this one bounded trial alone.

## Verification and delivery

The implementation adds `src/smartci/maven.py`, CLI wiring, `maven/action.yml`,
`action/maven_bootstrap.py`, release pins, focused tests, and the bounded HttpClient
workflow/helper examples. README and plan preserve the negative results and link
this operating-range evidence. [Hosted safety checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/46121882856)
passed **1,218 tests**, formatting, lint, typing, system-Python bootstrap checks and
the reproducible wheel hash gate before the valid comparisons.

1. Open each linked PR's comparison run. Inspect the native full step and published
   Smart Action step, not merely the green comparison badge.
2. Download `matched-httpclient-1` and `smartci-maven-paired-1`. Compare
   `selection.json`, `execution.json`, `result.json`, cache receipts and native
   Surefire/Failsafe XML. PR #2 must show native exit 1 in both arms and the exact
   failure above; PR #3 must show full fallback and 3,165 executed cases.
3. Inspect the [machine-readable record](httpclient-maven-2026-11-28.json) for
   immutable revisions, all attempts, timings, cache/evidence hashes and hardware.
   The [Action guide](../maven-action.md) describes integration and eligibility.
   No AWS deployment, model key or separately operated CLI service is needed.

The defensible conclusion is **observed savings from avoiding uncached native
modules under a narrow reviewed contract**. Repeatable standalone PR savings and
lifecycle return on investment remain unverified.
