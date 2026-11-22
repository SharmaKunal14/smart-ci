# Comparing native build graphs with source and runtime analysis

The active product goal remains unmet. A useful selector must save end-to-end
time while retaining the tested profile's correctness, not merely identify fewer
test files. All performance observations below come from GitHub artifacts.

| Approach | Observed result or current state | Engineering consequence |
|---|---|---|
| Compiler/import graph with cached base evidence | [date-fns PR #7](https://github.com/SharmaKunal14/date-fns/pull/7) narrowed execution, but setup, fetching and planning exceeded saved test time. | Fast native suites leave little overhead budget. Precomputation alone does not establish net savings. |
| Conservative Python import graph | [Textual PR #5](https://github.com/SharmaKunal14/textual/pull/5) retained full fallback after resolving some static gaps. | Computed loaders and resources require explicit supported semantics; clearing warnings is not sufficient. |
| Runtime observation | [Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6): 387s native versus 755s instrumented; same 3,467 outcomes. Observed examples/resources outside the configured roots. | Useful onboarding evidence, expensive in the PR path, and absence of observations cannot justify omissions. |
| Native build graph | Abseil's original baseline and systemd-only intervention failed. A complete baseline passed after also masking the separate Apport crash-report hook; selection and speedup remain unverified. | Use the documented runner policy on both comparison arms. Native caching, configuration, build-only scope and undeclared inputs remain acceptance gates. |

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

The native `bazel test ...` also builds non-test targets. Replacing `...` with
only impacted test labels can silently remove build checks. Reconcile native
build-only target/configuration results as well as tests; preserve that build
coverage in the selected arm and include its cost. Explicitly list all native
flags and runner settings that each arm inherits. A declared graph alone does
not prove hermetic runtime access: Bazel's [test specification](https://bazel.build/reference/test-encyclopedia)
requires declared dependencies but says that requirement is not fully enforced.
Undeclared resource access remains a compatibility limitation, not something an
agent's confidence can waive.

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
The current harness checks the complete tracked tree outside `.smartci/` and
`.github/workflows/`, disables external diff/text conversion and replacement
objects, and rejects untracked inputs, including ignored files copied by the
native script. The first full resource experiment used the previous path-based
guard; its complete Git diff was independently checked to contain only harness
and workflow changes. This hardening does not change that experiment's inputs.

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

The [corrected diagnostic PR #2](https://github.com/SharmaKunal14/abseil-cpp/pull/2),
[run 45064543249](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45064543249),
passed all **30 native cases** in the complete function-reference target. BEP
records 1.035 seconds for its test process; the job took 364 seconds, including
the large image pull, configuration and 324 compile actions. The earlier full
attempt timed this same target out after 71.541 seconds. That difference points
to full-workload/runner conditions but does not isolate their cause. Available
memory remained above 13,191 MiB in this one-target run. Five-second samples saw
no crash helpers; a one-second test can easily fall between samples, so absence
does not establish that no helper ran. The kernel routes crashes to systemd-coredump.

Two earlier setup attempts failed before executing tests because shallow history
omitted the pinned upstream object. The corrected workflow fetches that history;
the existing hardened event reconciler is included. [Hosted tool checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/45064538246)
passed 546 tests, formatting, lint, types and builds. The [durable record](../benchmarks/abseil-diagnostic-2026-11-23.json)
includes all setup attempts, exact revisions, hashes and scope limits.

The next full native attempt uses the **same application, tests, compiler,
assertions, signal handler and native command**, with a documented disposable-runner
policy: systemd-coredump `Storage=none` and `ProcessSizeMax=0`. These disable unused
system crash payload/backtrace processing while retaining log entries, according
to [systemd's documentation](https://www.freedesktop.org/software/systemd/man/latest/coredump.conf.html).
No Abseil source references core-dump files, core patterns or RLIMIT_CORE at this
pin. This is an environment intervention to evaluate, not proof of the suspected
cause. A successful run would establish a new baseline under that explicit policy;
it would not retroactively make the original failed run valid.

The workflow checks the existing handler, records and validates effective policy,
restores the previous configuration, and captures resource samples throughout the
full native command. All test targets must pass with a complete event stream;
flaky, failed or unknown targets prevent accepting the baseline. The native and
Smart CI comparison arms must use the same runner policy. No model calls or test
omissions are involved in establishing this baseline.

That [full attempt on PR #3](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45066014954)
also failed after 1,293 seconds from trigger to completion. Of 252 announced
targets, 177 passed, one failed, one timed out and one was flaky; 72 outcomes are
unknown. It reached the native process limit and container cleanup also timed out.
The runner policy was restored successfully. The [durable record](../benchmarks/abseil-resource-baseline-2026-11-23.json)
includes partial-result counts, artifact hashes and the complete failure status.

Resource sampling now establishes severe pressure: available memory fell to
45 MiB, all 3,072 MiB of swap was consumed, and the kernel's OOM-kill counter rose
by 81. Samples counted up to 413 `apport` processes. This strongly implicates
crash-report activity but does not attribute memory conclusively: per-process
resident memory and states were not recorded. Systemd's policy alone was not a
sufficient intervention. Upstream Apport installs an [OnSuccess hook](https://github.com/canonical/apport/blob/main/data/systemd/systemd-coredump%40.service.d/apport-coredump-hook.conf)
that starts a [separate crash-report service](https://github.com/canonical/apport/blob/main/data/systemd/apport-coredump-hook%40.service)
after systemd-coredump. Verify the installed hook before testing its temporary
suppression on a fresh disposable runner. Retain native signals, assertions,
test coverage and failure propagation. There is still no accepted full baseline
and no selection speedup.

The next attempt retains the same native profile and systemd storage policy,
verifies the runner's installed Apport `OnSuccess` relationship and executable,
then masks only `apport-coredump-hook@.service` for that disposable runner's
lifetime. It verifies the mask and restores the unit after execution, including
failure paths. It does not suppress native signals, assertions or test failures.
Helper telemetry now also aggregates process states and resident-memory fields;
missing observations remain explicit, and shared RSS pages can be counted in
more than one process. No raw status records, arguments, environments or core
payloads are retained. The complete native run must pass before this runner
policy can be used on both sides of a benchmark.

## Verified full baseline with the Apport hook bounded

[Run 45073921737](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45073921737)
on [PR #3](https://github.com/SharmaKunal14/abseil-cpp/pull/3), at
`6da46d213f16f99b80f57f9d861792bb793923a9`, passed **252 of 252 native test
targets** and all **576 build target/configuration results**. The complete
announced BEP stream reconciles, native exit is zero, and the generated full
profile script hash matches the original. No targets are flaky, failed or missing.

| GitHub measurement | Observed value |
|---|---:|
| Workflow creation to native job completion | **932 seconds (15m 32s)** |
| Runner job duration | 930 seconds |
| Native command, including image setup and build/tests | 922.107 seconds |
| Lowest sampled available memory | 10,253 MiB |
| OOM counter increase | 0 |
| Peak observed Apport helpers | 0 |

The installed hook, runtime mask and restoration were verified on the runner.
The prior systemd-only attempt observed 413 helpers and 81 OOM kills; this attempt
removed that observed resource exhaustion while preserving every native test and
assertion. It does not prove the cause of each earlier individual assertion failure.
The native compiler flags, image, timeouts, workers, caching and application source
are unchanged. The systemd and Apport settings are explicit environment changes,
and both were restored successfully.

This is **one accepted cold-profile baseline**, not a Smart CI speedup or evidence
of repeated reliability. The [durable record](../benchmarks/abseil-apport-baseline-2026-11-23.json)
contains hashes, exact timings, all test results and the 324 build-only labels.
Those labels include six `cc_test` rules built but not executed by native policy;
do not infer execution eligibility just from a rule's class. Future comparisons
must retain those build checks and use identical runner policy in both arms.
The diagnostic implementation passed [554 hosted safety tests](https://github.com/SharmaKunal14/smart-ci/actions/runs/45073891737),
formatting, lint, typing and distributable builds. The next step is real graph
collection and automatic planning, followed by paired native/selected PR runs.

To verify this milestone, open the successful run, inspect **Run complete native
profile with resource telemetry**, then download `native-resource-baseline-1`.
`native-resource-baseline/diagnostic.json` records zero exit/error and all 252
passed targets; `native.bep.json` records the native build graph's complete result
events. `runner-policy/` contains the installed hook and before/effective/restored
settings. No model secret, deployment, merge or test omission is required to inspect
these results. The earlier failed runs remain linked above and are not baselines.
