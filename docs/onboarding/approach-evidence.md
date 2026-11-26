# What the hosted experiments establish

The strongest measured result is currently the native build-graph adapter on a
localized Abseil change. Static imports, runtime observation and model assistance
remain useful mechanisms with different limits; none establishes arbitrary-repo
support. A smaller selected list alone is not a successful optimization.

All numbers below come from actual GitHub workflows. The rows use different
repositories and measurement boundaries, so they are not a controlled ranking of
algorithms. Exact revisions, profiles, artifacts and limitations remain in the
linked experiment records.

| Approach and real workload | GitHub result | What follows |
| --- | --- | --- |
| TypeScript import analysis, date-fns historical fix | Three-attempt median trigger-to-job result: 24 s native, 38 s optimized Smart CI; 4/253 files selected. [Run](https://github.com/SharmaKunal14/date-fns/actions/runs/44912659497), [record](../benchmarks/date-fns-optimized-2026-11-22.json). | The native suite is already fast. Reduced planning and fewer tests did not overcome setup overhead. |
| Precomputed TypeScript maps, same date-fns fix | Three-attempt median trigger-to-job result: 27 s native, 39 s rebuilt maps, 58 s authenticated cached maps. [Run](https://github.com/SharmaKunal14/date-fns/actions/runs/44915242036), [record](../benchmarks/date-fns-precomputed-2026-11-22.json). | Caching reduced planner work but its retrieval job and dispatch increased total latency. |
| Runtime observation, Textual parser regression | Trigger-to-job result: 350 s native, 570 s observed; all 3,467 case identities/outcomes/skips matched, no omissions. [Run](https://github.com/SharmaKunal14/textual/actions/runs/45043961511), [record](../benchmarks/textual-scoped-runtime-2026-11-23.json). | Observed dependencies did not prove exclusive ownership of shared/thread activity. Both checks remained red for the actual defect. |
| Bounded live investigator, evidence from Textual PR #11 | Three model calls, zero accepted new edges, unchanged full plan. The investigation/control workflow took 85 s and executed no Textual tests. [Run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062767011), [record](../benchmarks/textual-live-investigation-2026-11-23.json). | The controlled tool loop works, but this trial demonstrates no useful selection improvement or CI savings. It is disabled. |
| Native Bazel graph plus authenticated map reuse, localized Abseil fix | PR-event-to-completed-workflow pairs: 626/413 s and 724/497 s native/Smart CI. Savings: 34.0% and 31.4%. Both selected 2/252 test targets and retained all 324 build-only targets. [First record](../benchmarks/abseil-automatic-execution-2026-11-26.json), [repeat record](../benchmarks/abseil-automatic-repeat-2026-11-26.json). | Two cold pairs show a useful, repeatable benefit for this workload. They do not establish a representative average or warm-cache benefit. |

The native approach has stronger declared dependency evidence for its supported
source changes and can avoid substantial compilation as well as tests. It still
depends on a reviewed build profile and its declared-input assumptions. Broad
changes can reach almost everything: the earlier Abseil shared-hash comparison
selected 251/252 tests and took 924 s versus 640 s native. Preserve that negative
result rather than extrapolating the localized savings to all PRs. See the
[native evidence and scope](native-build-graphs.md).

Native startup logs show different CPU models within both passing Abseil pairs.
The same Ubuntu runner label and container do not hold hardware constant. The
34.0% and 31.4% values describe observed GitHub latency reductions, not isolated
causal estimates. Fewer executed native actions (2,988 to 1,092) are separate
evidence of reduced work. Preserve the runner identities and all timing attempts.

The deterministic selector remains the authority in every approach. Missing or
incompatible evidence requires reconstruction or full execution; an agent cannot
remove mandatory tests, waive unresolved dependencies or turn its confidence into
completeness evidence. More agents or votes would not fix this logical limitation.
The live verifier currently accepts only supported imports, so its failure to
narrow Textual's full fallback is unsurprising. A useful future agent contribution
needs a new mechanically verifiable dependency contract, not just a stronger
prompt. This is an inference from the current verifier and trial, not a general
claim that models cannot help.

The new native runner now preserves the regression's two compiler failures and
rebuilds a missing map from the passing base before restoring the broken PR head.
See the [execution lifecycle evidence](bazel-execution.md#native-regression-preservation).
The new-target/full-fallback comparison also passed: both arms discover all 253
current targets, including the test absent from the saved map. It takes 665 seconds
native versus 1,068 seconds Smart CI, performs identical work, and demonstrates
no saving. Almost all elapsed difference is inside the native command; the two
hosts have different CPUs. See the [fallback record](../benchmarks/abseil-automatic-fallback-2026-11-26.json).
Before broader rollout, finish the shared-change comparison. Report reconstruction and
enrollment costs separately and examine representative caching. The current public
Abseil profile lacks credentials for its optional upstream private remote cache;
the cold results do not describe that private environment. No merges, AWS
deployment or new model calls are needed for these remaining native checks.
