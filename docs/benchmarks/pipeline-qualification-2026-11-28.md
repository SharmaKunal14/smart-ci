# Qualify avoidable native work before another adapter

The warm Abseil negative result remains a control, not a result to replace.
This follow-up first inspects existing public CI evidence and then reproduces
one bounded native profile. Upstream timings below are qualification evidence,
not measured Smart CI savings. No merges, model calls or AWS work are authorized.

## Read-only screen

| Repository | Existing evidence | Decision |
| --- | --- | --- |
| FasterXML/jackson-dataformats-binary | Three recent native CI runs take 43–56 seconds per JDK job with Maven dependency caching. [Example](https://github.com/FasterXML/jackson-dataformats-binary/actions/runs/45326393832). | Too little demonstrated headroom for this milestone. |
| testcontainers/testcontainers-python | Its native community workflow already computes changed modules before its test matrix. [Pinned workflow](https://github.com/testcontainers/testcontainers-python/blob/6146aa1170f415fcc825ed9bddc4eacbeb937a12/.github/workflows/ci-community.yml). | Do not remove existing selection to create an inefficient baseline. |
| assertj/assertj | Native Java jobs take several minutes and restore Maven caches. Its pinned pipeline also instruments Maven through TestLens, whose setup requires a GitHub App and sends an authentication token to that service. [Example run](https://github.com/assertj/assertj/actions/runs/45900011390). | Defer; a faithful fork baseline needs resolving that existing service integration. Do not silently remove instrumentation. |
| testcontainers/testcontainers-java | Native CI uses a generated task matrix and Develocity remote cache. Recent PR records were awaiting approval, so those records contain no native timing evidence. | Defer; matrix generation alone does not establish avoidable uncached work. |
| apache/pdfbox | Its GitHub workflows expose CodeQL runs, not the required native test pipeline baseline. | Do not mistake static-analysis duration for test duration. |
| apache/httpcomponents-client | Native Linux/JDK 21 job took 226 s, including 219 s in Maven. Its log confirms a primary Maven cache hit and 132 s in the integration-test module. [Native run](https://github.com/apache/httpcomponents-client/actions/runs/45795779295/job/139825918638). | Reproduce and inspect before implementing selection. |

## Candidate and stopping conditions

Pin HttpClient source to `5b9837710dc84eb49c6d1fb0e70ba3b1174cd5e6`.
Start with its existing Linux/JDK 21 lane: Maven runs on JDK 17, compilation/tests
use its declared JDK 21 toolchain, `-Pdocker` stays enabled, parallel JUnit
execution stays disabled and the existing `clean verify` default remains.
Existing tests, native caches, checkstyle, license/API checks and failures are
preserved. This is one lane, not a claim about the complete nine-lane matrix.

The concrete dependency question is whether a Jakarta REST client source change
can omit the expensive integration-test module. The declared Maven reactor puts
the REST client on the core HttpClient dependency path; the expensive integration
module depends on core/cache/fluent/WebSocket, not the REST client. Native
effective models and test/runtime-input behavior must substantiate the boundary.
Do not infer independence from directories or from missing coverage.

The fork's first workflow runs only the unchanged native full command, captures
effective Maven models and native test reports, and publishes one bounded base
dependency cache. Cache publication is not a speedup. It is charged as enrollment.
No selector is active at this stage. Inherited workflows are removed only on the
isolated evaluation base, preserving their source history and the native command.
No publication/deployment workflows or third-party account connections are run.

If the working full baseline fails or Maven metadata cannot justify the boundary,
retain the failure/incomplete result and do not enable omissions. Supported
module selection, if justified, must use automatic native metadata, include
transitive consumers and required upstream builds, and retain full fallback for
configuration/build changes, unknown paths and invalid evidence. New/changed
tests remain in their module's native execution. A metadata match alone does not
prove arbitrary runtime independence.

## Bounded comparison after qualification

Only after the native qualification passes, implement the smallest CLI/Action
path needed for this profile. Compare the unchanged native full command and
candidate on real PRs: a localized maintenance change, a behavioral regression
with existing tests, and a build/configuration fallback. Start with one passing
comparison and inspect it before repetition. Target three passing repetitions;
retain every failed, slow, invalid or cache-miss attempt. No automatic broadening
to more repositories or a full matrix.

Prefer same-VM paired evidence with independent base dependency-cache restores,
fresh source/build outputs, balanced order and explicitly equal container-cache
conditions. Also measure actual complete PR and runner time, including setup,
metadata collection/planning, native execution, reports and cleanup. A joint job
running both approaches is not a standalone customer PR latency. Report actual
uncached test/case outcomes and missed failures against the full control; a
passing case cannot establish recall. Distinguish savings in runner work from
the complete workflow's longest required path.

Proposed useful-benefit gate: at least 20% repeatable reduction in the supported
warm-profile execution lifecycle, including Smart CI overhead, with no observed
missed control failures and separately reported enrollment/refresh costs. This
is an acceptance target, not a claim of present success or universal safety.

Bounds: one qualification job, maximum 20 minutes; at most five subsequent paired
jobs, maximum 20 minutes each; one active native job at a time; no unbounded
retries. The 120-minute sum is a timeout ceiling, not an expected cost. One cache
is capped at 2 GiB/100,000 files and deleted after consumers finish. Artifacts
expire after seven days. No paid runner/storage-limit increases or model calls.

## Qualification result and paired protocol

[Native qualification](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46118291884)
passed at isolated base `e2a3100cb62a4f9db45ea7dcb9c536178a69a0aa`.
Native Maven took 231.700 s; effective-model capture added 2.634 s; the complete
runner job took 253 s. There were 325 native XML reports with 3,183 testcase
outcomes: 3,165 passed and 18 native skips, no failures/errors. The source remained
clean. Enrollment published 182,217,417 raw cache bytes (150,944,345 compressed).
This is baseline/enrollment evidence, not Smart CI savings.

The reviewed experimental Maven profile is documented in [the Action guide](../maven-action.md).
It retains all POM aggregators and requires the enrolled native base-tree digest;
later native base changes require renewed review. This restriction must be counted
as a lifecycle limitation. It does not claim universal automatic Maven onboarding.

The first PR makes a behavior-preserving REST URI cleanup: calculate the final
base-path index once before reading/removing the empty trailing segment. Native
tests stay unchanged. Repeat that same PR at most three times, alternating order
full/Smart/full, after inspecting the first attempt. The regression PR restores
the historical double-slash bug in implementation only; existing regression tests
remain. The final POM-comment change exercises global configuration fallback.
Any failed setup consumes an attempt and is retained, not silently replaced.

Each paired job has the same physical runner, JDKs, source revision and native
flags. Each arm starts from a fresh clone and independently restores the exact
qualified Maven repository cache, verified by its tree digest. Native build output
is never transferred between arms. Maven wrapper cache is removed between arms;
Docker images/layers are cleared with no active containers, matching the native
ephemeral runner's uncached container setup. Docker pulls remain timed native work.
This is **warm Maven dependencies, cold wrapper/container state**, not a warm test
result cache. Filesystem page cache is reset before each arm and that reset is timed.

Arm intervals include checkout preparation, cache transfer/validation, reset,
Action setup/CLI installation (Smart only), metadata/planning, native execution,
the arm's evidence upload and report accounting. Shared JDK/tool setup, queue,
joint upload and cleanup remain in the complete paired PR/job timing and are
reported separately. The joint job is not measured standalone full-vs-Smart PR
latency; do not relabel a computed allocation as an observed standalone run.

Attempt 1, [run 46120604265](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46120604265),
failed in setup: the system Python evaluated an unsupported generic argparse
annotation while importing the new helper. Neither native arm ran. The whole
run took 26 s and the job 23 s. Retain it in total costs. Postponing annotations
and adding a system-Python bootstrap import check fixes the cause. Within the
original five-job cap, four attempts remain: two passing comparisons with reverse
order, one regression and one configuration fallback. Three valid passing
repetitions will therefore not be claimed.

Attempt 2, [run 46121221251](https://github.com/SharmaKunal14/httpcomponents-client/actions/runs/46121221251),
passed the full native arm but refused to prepare the candidate while a native
container remained active. There is no candidate performance result. The
measurement helper now waits at most 45 seconds for native cleanup, records the
observed containers and charges that cleanup to its owning arm. It still refuses
to continue if any container persists. No active container is forcibly erased to
manufacture independence. Three attempts remain: one passing pair, one regression,
one configuration fallback. The initial repeatability target is not satisfied.
