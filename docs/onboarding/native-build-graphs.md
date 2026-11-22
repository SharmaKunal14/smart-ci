# Comparing native build graphs with source and runtime analysis

The active product goal remains unmet. A useful selector must save end-to-end
time while retaining the tested profile's correctness, not merely identify fewer
test files. All performance observations below come from GitHub artifacts.

| Approach | Observed result or current state | Engineering consequence |
|---|---|---|
| Compiler/import graph with cached base evidence | [date-fns PR #7](https://github.com/SharmaKunal14/date-fns/pull/7) narrowed execution, but setup, fetching and planning exceeded saved test time. | Fast native suites leave little overhead budget. Precomputation alone does not establish net savings. |
| Conservative Python import graph | [Textual PR #5](https://github.com/SharmaKunal14/textual/pull/5) retained full fallback after resolving some static gaps. | Computed loaders and resources require explicit supported semantics; clearing warnings is not sufficient. |
| Runtime observation | [Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6): 387s native versus 755s instrumented; same 3,467 outcomes. Observed examples/resources outside the configured roots. | Useful onboarding evidence, expensive in the PR path, and absence of observations cannot justify omissions. |
| Native build graph | Abseil's unchanged native baseline failed and timed out; graph parsing is implemented, selection and speedup unverified. | A declared graph cannot repair an unreliable native baseline. Native caching, configuration, non-test builds and undeclared inputs remain acceptance gates. |

The existing [Bazel query](https://bazel.build/query/language) graph includes all
possible `select` branches. This is conservative with respect to declared build
dependencies, not proof of every runtime dependency. The parser keeps rule
inputs, generated-file generators, external tool dependencies and non-test rules.
It rejects malformed XML, DTDs/entities, duplicate nodes, dangling edges, unknown
target forms and excessive graph/witness sizes. Unknown changed files raise an
error instead of producing an empty affected set. Witness ordering is stable for
fixed inputs. It does not change the current selector or grant skip authority.

## Abseil baseline

- Upstream pin: `82530019412ff77ff99d39ba0ad12e5ea6b89ea4`.
- Fork: [SharmaKunal14/abseil-cpp](https://github.com/SharmaKunal14/abseil-cpp).
- Isolated default branch: `codex/smartci-native-base`; upstream `master` is preserved.
- Baseline: [PR #1](https://github.com/SharmaKunal14/abseil-cpp/pull/1).
- Command: the existing `ci/linux_gcc-latest_libstdcxx_bazel.sh` with `STD=c++17`,
  `COMPILATION_MODE=fastbuild` and `EXCEPTIONS_MODE=-fno-exceptions`.
- Native pinned public container and toolchains retained; anonymous manifest
  inspection found 6,071,717,950 compressed layer bytes. That is an image size,
  not a benchmark measurement. No credentials or private remote cache are used.
- The wrapper only adds a unique Docker container name and a native Build Event
  Protocol output path through upstream hooks. It does not disable test-result
  caching, change test tags, change worker settings or alter application/tests.
- One Ubuntu 24.04 job, 25-minute job limit, 20-minute native process limit,
  read-only permissions and seven-day artifacts. Timeout cleanup targets only
  the uniquely named container created by that invocation.

The wrapper counts native **Bazel test targets**, not internal C++ cases. Native
failures and timeouts remain failing checks. Missing, incomplete or contradictory
event evidence also fails the check. Validation requires the announced event graph,
including build-only results, to be present exactly once, with a genuine terminal
message. A success marker alone is insufficient. This follows the native
[BEP announcement structure](https://bazel.build/remote/bep-examples) and
[completion semantics](https://bazel.build/remote/bep-glossary).

### Observed failure, not an accepted performance baseline

[Run 45038161080](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45038161080),
job `native` (`137256408107`), failed at head
`8711caddc87b1f4e0b84b3d825deb1ab7f7347ba`. The saved summary is
[`abseil-native-2026-11-23.json`](../benchmarks/abseil-native-2026-11-23.json).

- The native event stream announced **252 test targets**. Before interruption,
  only **192** produced summaries: **190 passed, one failed, one timed out**.
  The other 60 outcomes are unknown, not passes or skips.
- `//absl/synchronization:mutex_test` failed its existing elapsed-time assertions.
  `//absl/functional:function_ref_test` exceeded its native test timeout.
- The full command reached the wrapper's 20-minute bound. The uniquely named
  container's cleanup also exceeded its separate 20-second bound. No complete
  build-finished or terminal event exists in the downloaded artifact.
- Workflow creation to job completion was **1,450 seconds (24m 10s)**, including
  setup, test/build work, timeout handling and GitHub cleanup. This is the duration
  of a **failed attempt**, not the duration of a completed full suite.
- There was no selective execution and no Smart CI speed comparison. The image
  pull, native failures and cleanup remain part of the recorded outcome.

The failure logs establish the assertions and timeouts, but do not identify their
underlying resource cause. CPU contention, memory pressure or disk activity are
hypotheses; resource telemetry was not collected. Increasing time limits would
not by itself fix the native failures. Do not remove these tests, switch profiles
silently, or rerun until a green sample can be reported. This profile needs a
diagnosed intervention and an independent successful baseline before comparison.

To inspect it, open the run above, expand **Run unchanged upstream native profile**,
then download `abseil-native-1`. `execution.json` preserves exit 124 and the cleanup
error; `native.bep.json` preserves the partial results. Artifact hashes are saved
in the summary. Neither file is promotable evidence for skipping tests.

The graph parser and original wrapper passed the separate
[Smart CI safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45041331271):
344 tests, formatting, lint, typing and wheel/source build. That verifies the
implementation's checks, not the failed Abseil workload or a performance benefit.

## Remaining delivery work

After the native profile succeeds, collect actual query output in the same
toolchain, reconcile it with native target events, bind build definitions and
environment identity, and implement automatic PR execution. Configuration,
dependency-definition, unsupported file and incomplete-evidence changes must
retain full fallback. Do not assume a parsed XML graph is a complete native test
inventory. Verify deleted/renamed files and dependency changes against both
revisions, preserving removed edges.

Compare eligible historical source changes against the independent full native
command on real PRs. Retain ordinary native build/test caches; Bazel itself may
already avoid unchanged work, so this approach may provide little additional
benefit on warm runs. Report any such negative result. A cold-only advantage
must be labeled as such and must not be generalized to cached enterprise CI.

Agentic investigation remains a separate active-goal gate. No live model or
agent benefit is claimed by this baseline or parser. No AWS deployment or merge
is involved.

## Bounded native failure diagnostic

The regular-API agent trial is now implemented separately and has shown no
selection benefit on Textual. To make progress on the end-to-end goal, first
diagnose the failed native environment rather than weakening the selector or
promoting a partial baseline.

`examples/abseil/diagnostics.py` derives a diagnostic from the exact pinned native
GCC script. It changes only `bazel test ...` to the complete
`//absl/functional:function_ref_test` target and requests full test log output.
Source, test bodies, assertions, timeouts, compiler flags, signal-handler setting,
Docker image, workers and caching remain unchanged. The full profile script hash
must match before derivation; application/build files must match the upstream pin.

This is a manually scoped failure investigation, **not automatic test selection,
a successful full-suite baseline, or a Smart CI speed comparison**. It preserves
native failures and requires complete Build Event Protocol evidence for precisely
that one target. The job has a 14-minute bound and a 10-minute process bound, with
cleanup restricted to its uniquely named Docker container.

Five-second samples record CPU, memory, swap and I/O-pressure counters, kernel
core-dump settings and counts of known crash/symbolizer helper names. They do not
read process arguments, environments, stacks or core contents. Crash handling is
one hypothesis: Linux's [core documentation](https://man7.org/linux/man-pages/man5/core.5.html)
explains that piped core handlers run outside a container's namespaces and that
`RLIMIT_CORE` does not suppress those handlers. Their presence would not by itself
prove that they caused the observed timeout. No kernel setting is changed by this
diagnostic, and no resource-cause claim is justified until hosted evidence exists.
