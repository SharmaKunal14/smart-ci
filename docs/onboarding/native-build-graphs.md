# Comparing native build graphs with source and runtime analysis

The active product goal remains unmet. A useful selector must save end-to-end
time while retaining the tested profile's correctness, not merely identify fewer
test files. All performance observations below come from GitHub artifacts.

| Approach | Observed result or current state | Engineering consequence |
|---|---|---|
| Compiler/import graph with cached base evidence | [date-fns PR #7](https://github.com/SharmaKunal14/date-fns/pull/7) narrowed execution, but setup, fetching and planning exceeded saved test time. | Fast native suites leave little overhead budget. Precomputation alone does not establish net savings. |
| Conservative Python import graph | [Textual PR #5](https://github.com/SharmaKunal14/textual/pull/5) retained full fallback after resolving some static gaps. | Computed loaders and resources require explicit supported semantics; clearing warnings is not sufficient. |
| Runtime observation | [Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6): 387s native versus 755s instrumented; same 3,467 outcomes. Observed examples/resources outside the configured roots. | Useful onboarding evidence, expensive in the PR path, and absence of observations cannot justify omissions. |
| Native build graph | Abseil PR #6 passed two cold comparisons: 252 native test targets versus 2 selected, with all 324 build-only targets retained. Candidate trigger-to-result reductions were 70.3% and 47.7%. | The paired workflow still waits for its full control. A single-job workflow, broad-change results and warm-cache behavior must be distinguished from candidate-job savings. |
| Bounded model investigation | [Textual live investigation](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062767011): three calls, zero accepted new edges, all 14 gaps unresolved. | Agent proposals remain subordinate to deterministic validation. This trial demonstrated no selection or speed benefit; the campaign is disabled. |

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

## Native graph audit

The next collector runs `deps(//...)`, `//...` and `buildfiles(deps(//...))` queries
using the same pinned native container and Bazel 9.1.0. It does not execute tests.
Query deliberately retains all configuration branches; execution eligibility is
taken from the independently completed native reference, not inferred from test
rule names. The collector checks the reference run identity and exact BEP hash,
requires complete successful native results, and verifies that every observed
build/test root exists in the parsed graph. Build-only targets, configurations,
manual/excluded query roots and source witnesses remain separate in the audit.

`examples/abseil/query-workflow.yml` is a template: replace `REVIEWED_TOOL_COMMIT`
with the reviewed Smart CI commit before installing it on the fork. Its job is
branch-limited, read-only, bounded to 14 minutes and carries no model credentials.
The reference download token is scoped to its own workflow step. Native query
execution receives an explicit minimal environment. Unsupported or partial graph
evidence fails the audit; it cannot authorize omissions. Production profile and
runtime-dependency eligibility remain additional requirements.

The following upstream changes were chosen **before** querying graph breadth.
Counts from this audit are potential impact, not executed PR selections or speed
measurements. Keep broad and negative cases in the later comparison:

- [Cord suffix comparison optimization](https://github.com/abseil/abseil-cpp/commit/da428eb4893dbb1403634ab0fed96a9a0cab9836): `cord.cc` and `cord.h`.
- [Const-span regression fix](https://github.com/abseil/abseil-cpp/commit/8380c9eb674392b3a2ac50488a9f0df0e438b24e): `span.h`, retaining its regression tests when replaying faulty production behavior.
- [Linked hash node insertion fix](https://github.com/abseil/abseil-cpp/commit/745e8f3eb8b5b9342fb658d94994ba349212f107): both public linked-hash container headers, retaining their regression tests.
- [Shared hash implementation change](https://github.com/abseil/abseil-cpp/commit/82530019412ff77ff99d39ba0ad12e5ea6b89ea4): `hash.cc` and `hash.h`.

A build/dependency-definition change must also retain the independent full native
path. These four source cases cannot by themselves establish that fallback or
safe handling of removed dependencies works.

The [first hosted query](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45082915973)
failed with exit 7: the all-branches closure required optional `libpfm` and its
selected registry entry pointed at an unreachable `netcologne.dl.sourceforge.net`
mirror. Its partial XML was rejected. No test selection or execution occurred.
The native reference did not need that optional dependency in its configured build.

The repair seeds Bazel's [distribution archive cache](https://docs.bazel.build/versions/main/guide.html#distribution-files-directories)
from the [replacement URL published by the Bazel Central Registry](https://github.com/bazelbuild/bazel-central-registry/blob/main/modules/libpfm/4.11.0.bcr.2/source.json).
Both registry releases pin the same archive SHA-256,
`5da5f8872bde14b3634c9688d980f68bda28b510268723cc12973eedbab9fecc`.
This changes only archive acquisition: the selected module version and patches
are untouched. HTTPS-only redirects, size and time bounds, and a checksum check
precede cache acceptance; Bazel verifies the checksum again. Download failure or
mismatch rejects the audit. Acquisition and total planning time are recorded,
and no dependency branch is excluded to make the query succeed.

The [repaired hosted query](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45083836757)
passed, retaining 2,614 nodes and 13,349 edges and reconciling all 576 native build
roots and 252 test targets. It acquired the identical archive in 0.618 seconds;
graph preparation, including the pinned image setup, took 261.334 seconds.
The [durable record](../benchmarks/abseil-graph-2026-11-23.json) binds raw artifact
hashes, revisions, native reference and both attempts.

The preselected scenarios produced mixed candidate breadth:

| Actual upstream source change | Candidate native test targets |
|---|---:|
| Cord optimization | 250 / 252 |
| Const-span regression | 251 / 252 |
| Linked hash node insertion regression | 2 / 252 |
| Shared hash implementation | 251 / 252 |

These broad paths are not parser noise: for example, `algorithm_test` depends
on GoogleTest, which depends on Abseil containers and RE2; those reach Cord,
Span and hashing. Removing those edges would remove real declared dependencies.
Only the linked-hash case currently offers a useful small candidate set. No
selective tests ran, so neither regression recall nor end-to-end savings is yet
established. The next comparison must validate map reuse against unchanged build
definitions and source inventory, retain the 324 build-only roots and native
runner settings, and execute independent full/selected arms on the same PR head.

## Paired native evaluation and map reuse

`src/smartci/bazel/planning.py` builds a deterministic candidate from the actual
base/head Git trees and authenticated hosted graph. Both revisions must preserve
the anchor's path inventory, file modes and every non-C++ input. Only modified,
existing, declared regular `.cc`/`.h` files are eligible. Missing or invalid map
artifacts, changed build definitions/dependencies/resources, unknown files,
additions/deletions/renames, mode changes, empty impact and invalid must-run rules
retain the original full command. Pilot setup files may differ from the anchor;
changing them within the PR also forces full fallback. Reuse of this declared
graph assumes the reviewed build profile does not derive topology from C++ file
contents. This is a profile compatibility assumption, not universal inference.

The pilot runner verifies exact PR checkout, clean tracked/untracked inputs,
native script and container definitions, artifact digests and successful reference
evidence. Two independent planning passes must produce the same digest. A selected
arm retains `...` and subtracts only omitted native test labels through Bazel's
target-pattern file. It does not replace the wildcard with a list of tests: all
324 native build-only targets remain required, together with their configurations.
The complete Build Event Protocol must reconcile selected tests and build scope.
Native failures, flaky outcomes and missing/mismatched evidence fail the check.

`examples/abseil/evaluation-workflow.yml` runs one native and one candidate job on
separate identical runners, with the same pinned image/compiler/options and
verified/restored crash-report policy. The native arm uses the original command
and standard-library wrapper; only the candidate pays for planner setup and
evidence downloads. Artifact or planner installation failure retains full native
execution. Jobs have 25-minute bounds, read-only permissions and no model secrets.
The independent full control remains required: this is an experiment, and no
production omission authority has been enabled. No cache settings are changed.

The first paired source case replays the historical hinted-node insertion bug
from upstream `745e8f3eb8b5b9342fb658d94994ba349212f107`. The old four-file patch
does not apply to this newer upstream pin: the method has moved into
`absl/container/internal/raw_linked_hash_set.h`. The replay changes the current
method between invalid `.first` and correct `.position`, keeping every current
test, including upstream's original regression assertions. This is an **adapted
historical regression replay**, not an exact cherry-pick. The base intentionally
contains the old defect; the positive PR fixes it, and both comparison arms test
the identical fixed head. A reverse PR on a fixed base will check failure recall.
Do not report a failing run as a successful performance baseline. Broad-impact
and configuration/full-fallback scenarios remain part of the evaluation.

The first candidate arm on [PR #5](https://github.com/SharmaKunal14/abseil-cpp/pull/5),
[run 45085741236](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45085741236),
ran the intended two tests and all 324 build-only roots successfully, but its
check failed during evidence validation. Bazel repeats the 250 exclusion names
in an announced target-pattern event ID; the 9,461-byte ID exceeded the reader's
original 4 KiB bound. The raw hosted evidence is retained, and this attempt is
not a passing benchmark. A narrowly validated exclusion-pattern form now has a
64 KiB/2,048-pattern bound; ordinary IDs retain the 4 KiB limit. Event announcement,
completion, duplicate detection and native scope checks are unchanged. Planning
falls back before execution when its exclusions exceed the supported size. Tests
cover both complete large-pattern events and malformed/missing/oversized forms.

The [second PR #5 attempt](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45086969708)
passed both arms, but correctly selected **full execution**: GitHub's event still
used the earlier base snapshot, so its diff included the workflow-pin update.
Both arms ran all 252 tests and retained 576 build/configuration results. The
candidate finished in 744 seconds and the native arm in 916 seconds; because
both executed the full suite, that difference is **runner variation, not selector
savings**. The [record](../benchmarks/abseil-workflow-fallback-2026-11-23.json)
preserves the exact event base separately from the subsequently refreshed PR base.

PR #5 was closed without merging. [PR #6](https://github.com/SharmaKunal14/abseil-cpp/pull/6)
has the corrected base, the same production head content, and exactly one changed
production line. It retains the repaired tool pin in both base and head. All
earlier attempts remain recorded, including the
[initial failed evidence check](../benchmarks/abseil-pair-attempt1-2026-11-23.json).
Hosted [Smart CI safety checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/45086538971)
passed formatting, lint, types, 613 tests and the package build on that tool pin.

### Accepted source-only comparison

[PR #6 run 45088718028](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45088718028)
passed both arms on the same head, `5b3e552a931ad12302fdff00f3688b806429ff44`.
Its only change fixes the shared hinted-node insertion implementation; all tests
and native build definitions remain unchanged. The
[record](../benchmarks/abseil-source-only-pair-2026-11-23.json) includes GitHub job
links, timing scopes, complete test identities, action counts and artifact hashes.

| GitHub measurement | Full native | Smart CI candidate |
|---|---:|---:|
| Workflow trigger to job completion | 1,061s (17m 41s) | 315s (5m 15s) |
| PR creation to job completion | 1,065s | 319s |
| Runner allocation to job completion | 1,059s | 312s |
| Passing native test targets | 252 | 2 |
| Required build-only targets retained | 324 | 324 |
| Bazel actions executed | 2,988 | 1,092 |

The candidate's **746-second / 70.3% trigger-to-result reduction** includes its
own setup, evidence downloads, planning and uploads. Planning took 1.380 seconds;
the native command, including container preparation, took 283.330 seconds. The
selector automatically chose `linked_hash_map_test` and `linked_hash_set_test`.
The recorded witnesses are native dependency paths, not handwritten test rules:
`linked_hash_map_test → linked_hash_map → raw_linked_hash_set → internal/raw_linked_hash_set.h`
and the equivalent `linked_hash_set_test → linked_hash_set` path to the same header.
Their configurations and all build-only configurations matched the authenticated
reference. Both arms restored runner settings, and neither recorded an OOM kill.
This is a measured candidate-arm saving, not a 70% improvement to the whole paired
validation workflow: that workflow still waits for the full control and consumes
both jobs' runner time.

Keep the limits explicit. This is one successful pair on separate cold runners;
successful full runs have varied from 632 to 1,061 seconds in the retained attempts.
The 283-second initial graph audit is a separate onboarding cost. The warm private
remote cache and other compiler/standard configurations are not measured. Passing
fix outcomes do not measure failure recall; the reverse regression, repeated
measurements and a subset-only eligible PR remain acceptance gates. Broad changes
still select nearly all tests. Production omission authority remains disabled.

### Compiler failure evidence

The reverse historical replay is [PR #7](https://github.com/SharmaKunal14/abseil-cpp/pull/7).
Its first candidate run selected the same two targets and exited 1 after both
failed compilation. Its 1,067-event stream was closed and retained all 326 required
build results, but contained no test summaries: neither test executable existed.
The original reader rejected that valid failed-build evidence as incomplete.
This is a reporting defect; the failed native exit was preserved, and the check
was never green. It is not a successful benchmark or yet a completed recall claim.

The repair accepts zero summaries only for native exit 1 with completed failed
build results and the entire announced event graph present. Evaluation accounts
for a missing selected test summary only when every recorded build configuration
of that exact target failed. Successful builds cannot excuse missing test outcomes,
contradictory passes are rejected, and all required build roots/configurations
remain checked. `failed_test_build_targets` records those targets separately;
`test_targets` continues to contain actual native test summaries. The command
still returns the native failure. Interrupted, truncated or aborted streams are
not accepted. This distinction follows the separate build-completion and test
summary events in the [Bazel protocol](https://raw.githubusercontent.com/bazelbuild/bazel/9.1.0/src/main/java/com/google/devtools/build/lib/buildeventstream/proto/build_event_stream.proto).

The [first full regression control](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45091357544)
completed too: 250 actual test summaries passed, and the identical two selected
targets failed compilation. Reconciliation with the repaired reader accounts for
all 252 native test targets and all build/configuration results; no failed native
target was omitted in this one replay. Both original hosted reports still contain
`EXECUTION_EVIDENCE_INVALID`, so the
[record](../benchmarks/abseil-regression-reporting-2026-11-23.json) labels this as
forensic reconciliation, not a clean hosted report or successful benchmark.
The repair's [hosted safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45092478298)
passed 624 tests, formatting, lint, types and package build. The subsequent live
PR attempt must verify the repaired reporting path before that gate is closed.

The [repaired PR #7 run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45098113404)
now verifies that path on head `1174e91618f3447b60727afbc075ae3b084beedf` and tool
`b3bce1969d6986be4b03bda101c687e64caf1c55`. Both jobs returned native exit 1 with
**no evidence error**. The full control reported 250 passing test targets and two
failed compilation targets; the candidate reported the identical two failed
compilation targets, with no executed test summaries. All 324 build-only targets
and required configurations were accounted for in both jobs. No failed native
target was omitted in this replay. Both PR checks correctly remain red.

The [durable record](../benchmarks/abseil-regression-2026-11-23.json) distinguishes
this accepted failure-detection evaluation from a successful performance baseline.
The candidate rejected the defect in 312 seconds from the update trigger; the
full control finished in 1,085 seconds. These are GitHub measurements of the same
faulty source revision, not local timing or a claim that two test cases executed.
One historical defect, repeated to repair reporting, is still one regression
scenario. Repeated passing comparisons, broad/fallback source scenarios and a
subset-only eligible PR remain open gates; no production omission authority is
enabled by this result.

## Opt-in single-job execution

The runner now accepts `--mode candidate --execution-mode selective`. Paired
evaluation remains the default; an independent `--mode native` cannot be relabeled
as selective. This policy belongs in the reviewed CI workflow, not PR-provided
configuration or agent output. The native profile, artifact provenance, exact
base/head trees, supported source changes, mandatory tests and complete native
result checks remain unchanged. Policy changes cannot remove dependency edges.

The core planner includes execution authority in its deterministic digest. Under
the selective policy, a valid subset authorizes those omissions and does not
require a second full-control job. A full-fallback decision authorizes no omissions
and executes the original full command once. Missing map data or planner installation
still selects that full path. Invalid execution evidence and native failures still
fail the check; they never become an empty green result.

`examples/abseil/selective-workflow.yml` is the template for the reviewed
Abseil profile. It has one candidate job, a 25-minute limit, pinned actions, read-only
permissions, the same runner policy and artifact verification, and no model secret.
Both the normal and standard-library fallback command paths explicitly select the
single-job policy. Its dedicated base/head branch filters avoid changing the
existing paired comparisons. Replace `REVIEWED_TOOL_COMMIT` with the verified tool
commit and install the workflow in the enrollment base before creating the source
PR. Do not claim a deployment or single-job saving until that real PR completes.

The fallback and repeat checks passed. [PR #10](https://github.com/SharmaKunal14/abseil-cpp/pull/10)
completed the explicitly enabled single-job policy on the one-line source fix.
Its verified result below includes exactly one test job, a validated subset, all
build-only work retained, complete outcomes and whole-workflow timing against
the matching independent native baseline.
Rollback restores the reviewed full-native workflow and runner policy. This remains
one supported native profile; it is not an arbitrary-Bazel-project installer.

## Build-definition fallback verification

[PR #8](https://github.com/SharmaKunal14/abseil-cpp/pull/8) renames the internal
linked-hash header and updates its Bazel/CMake declarations and public includes,
without changing test bodies. Its [GitHub run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45103078298)
passed both jobs. Smart CI reported `MAP_INPUTS_CHANGED` and
`UNSUPPORTED_OR_RISK_CHANGE`, retained the original native command byte-for-byte,
and ran all 252 test targets plus all 324 build-only targets. Full build/test
identities and configurations matched between jobs, with no evidence errors.

The native job finished 638 seconds after the trigger; the full-fallback candidate
finished in 665 seconds. Both ran everything, so there is **no selection saving**
in this case. The difference includes setup and runner variation; it is not a
measurement of planning alone. The
[record](../benchmarks/abseil-header-fallback-2026-11-23.json) binds both artifacts,
the original event revisions and the changed paths. CMake declarations were
updated but this run measured only the pinned GCC/Bazel profile, not CMake.

The preselected broad shared-hash case is an exact reverse of upstream
`82530019412ff77ff99d39ba0ad12e5ea6b89ea4`, changing only
`absl/hash/internal/hash.cc` and `absl/hash/internal/hash.h`. Current upstream tests
are retained. It is expected to have broad impact, and no useful speedup is assumed.
The paired template permits that one additional named branch; concurrency and
timeout bounds remain unchanged. [PR #9](https://github.com/SharmaKunal14/abseil-cpp/pull/9)
completed the comparison described below.

## Repeated passing comparison

Reopening PR #6 produced [run 45104438683](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45104438683)
on exactly the same base, head and tool pin as the original accepted run. Both
jobs passed. The candidate plan is byte-identical, including its deterministic
digest, selected test identities, dependency witnesses and build configurations.
All 324 build-only targets remain present. The
[repeat record](../benchmarks/abseil-source-only-repeat-2026-11-23.json) preserves
both artifacts and their hashes.

| Fresh GitHub trigger to result | Original accepted run | Repeat |
|---|---:|---:|
| Full native job | 1,061s | 619s |
| Candidate job | 315s | 324s |
| Candidate reduction | 70.3% | 47.7% |
| Native / candidate Bazel actions | 2,988 / 1,092 | 2,988 / 1,092 |

Planning in the repeat took 1.302 seconds. The native command, including container
preparation, took 291.020 seconds in the candidate. Its 324-second result includes
checkout, installation, authenticated map downloads, planning, execution, artifact
upload and cleanup. Both jobs restored runner policy. Fresh workflow creation,
not the original PR's age, defines the repeat's start timestamp.

Two pairs establish repeatability for one source change under this cold profile,
not a general speedup percentage. Native timing varied substantially, while action
counts were identical across repetitions. The shared-hash case below shows what
happens when a real change has broad dependency impact. Neither passing pair by
itself reduces the entire paired workflow's completion time or total compute.
The separate single-job result below measures whole-workflow savings.

## Broad shared-hash comparison: no useful benefit

[PR #9 run 45105549633](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45105549633)
passed both jobs. The automatically selected 251 test targets all matched the
passing full control; all 324 build-only targets/configurations remained present.
The [record](../benchmarks/abseil-shared-hash-2026-11-23.json) retains the negative
timing result and complete artifacts.

| GitHub measurement | Full native | Candidate |
|---|---:|---:|
| Trigger to job completion | 640s | 924s |
| Passing test targets | 252 | 251 |
| Bazel actions | 2,988 | 2,981 |
| Native command, including preparation | 619.218s | 901.635s |
| Bazel wall time | 476.554s | 630.792s |

Seven fewer actions is a 0.23% work-count reduction; the candidate took 284 seconds
longer. Planning took 1.678 seconds, so attributing the entire slowdown to planning
would be false. Both native execution and command time outside Bazel were slower
on the candidate's separate runner; this pair does not isolate their cause. Both
jobs had zero recorded OOM kills and restored runner settings. Do not generalize
the narrow-change gain to shared core changes or prune real dependency edges to
manufacture savings. This passing source change does not add a failure-recall case.

## Whole-workflow result and selective-policy fallback

The [single-job PR #10](https://github.com/SharmaKunal14/abseil-cpp/pull/10),
[run 45107669149](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45107669149),
passed. Its independent [native PR #3 repeat](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45106725231)
also passed. The complete application/build/test trees match byte-for-byte under
Git, excluding only `.github/workflows/` and `.smartci/`. Both used the same native
profile and runner policy. The [record](../benchmarks/abseil-single-workflow-2026-11-23.json)
binds the source tree digest, native outcomes, artifact hashes and timestamps.

| GitHub measurement | Native baseline | Smart CI |
|---|---:|---:|
| Actual PR event to completed workflow status | 655s (10m 55s) | 544s (9m 04s) |
| Workflow creation to completed status | 653s | 519s |
| Allocated runner time | 650s | 517s |
| Passing test targets | 252 | 2 |
| Build-only targets retained | 324 | 324 |
| Bazel actions executed | 2,988 | 1,092 |

The developer-facing result is **111 seconds / 16.9% faster from PR event to
completed workflow**, with 133 fewer allocated runner-seconds. The native start
is its recorded fresh PR-reopen event; the selective start is PR #10's creation.
These timestamps include GitHub event dispatch: two seconds before native workflow
creation and 25 seconds before selective workflow creation. Do not substitute the
20.5% workflow-creation reduction for the more complete PR-event result. There is
one test job in each workflow; the Smart CI PR does not wait for a second full job.

Selection and build/test outcomes match the earlier paired localized scenario.
Planning took 1.631 seconds. Candidate native-command time was 494.693 seconds,
including 248.874 seconds of Bazel wall time; native command time was 637.909
seconds, including 488.125 seconds of Bazel wall time. Command work outside Bazel
includes container preparation and copying; it is not measured as network time
alone. Candidate elapsed time varied substantially from the earlier pairs despite
identical action counts. This is a demonstrated saving for one supported cold
profile and localized change, not a stable universal speedup or a new regression
scenario. The graph audit's 283-second onboarding cost remains separate.

The same one-job policy also passed [PR #11](https://github.com/SharmaKunal14/abseil-cpp/pull/11),
[run 45108053153](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45108053153).
The header/build refactor produced `MAP_INPUTS_CHANGED` and
`UNSUPPORTED_OR_RISK_CHANGE`; no omissions were authorized. It executed the full
command once, with all 252 test targets passing and all 324 build-only targets
retained. Actual result identities, outcomes and build configurations match the
independent PR #8 full control. The workflow completed 661 seconds after creation,
with native exit 0 and no evidence error. The
[fallback record](../benchmarks/abseil-single-fallback-2026-11-23.json) retains its
complete plan/report and hashes. This is fallback verification, not a speedup.
Both standalone comparisons recorded zero OOM kills and restored runner policy.

## Product boundaries still open

The native collector discovers dependencies; nobody supplied per-test edges for
these PRs. However, enrollment of this pilot still uses a reviewed Abseil-specific
profile, pinned artifact references and a prepared CI workflow. It is not yet a
general `smartci` enrollment command for arbitrary Bazel repositories. Missing or
expired map artifacts fall back to full execution rather than rebuilding a native
map automatically. A changed native test inventory/profile requires re-enrollment;
the existing full-result reconciler otherwise rejects the unexpected scope. That
is a conservative failure, not seamless support for adding arbitrary test targets.

Warm-cache benefit is also unmeasured. The private upstream cache is unavailable,
and fresh hosted runners do not approximate its cache hit rate. Do not promise
the measured cold-profile savings for an enterprise system that already caches
most builds and test results. A general installer, automated map lifecycle and
representative cache evaluation remain delivery work even if the single-job pilot
demonstrates an end-to-end saving.
