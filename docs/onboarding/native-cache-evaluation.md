# Native cache comparison and measured limits

Status: implemented and verified on the corrected source-only regression pair.
The consumer revision passed [884 hosted safety tests and builds](https://github.com/SharmaKunal14/smart-ci/actions/runs/45797148522).
Smart CI selected 2/252 test targets and preserved the same two compiler failures,
but took **209 seconds versus 198 seconds native**. The passing pair also completed: **307 seconds Smart CI versus 289 seconds native**,
with 1/252 test targets selected. Neither valid warm pair shows a speed benefit.

The initial pair added workflows inside its PRs, correctly forcing full scope
(native 198 seconds, Smart CI 204 seconds). That setup error and both seed costs
are retained rather than discarded.
The current public Abseil profile has no credentials for upstream's optional
private cache. Its measured cold savings cannot establish savings in that private
environment. On 26 November 2026, the fork's GitHub cache-usage API reported zero
cache entries and zero stored bytes.

Bazel supports a filesystem action cache through `--disk_cache`. A separate,
explicitly identified profile can use it to study native reuse without deploying
a server. This will be a controlled cache configuration, not a reproduction of
upstream's private service. See [Bazel's cache documentation](https://bazel.build/remote/caching#disk-cache).

1. **Record a reviewed cache profile.** Preserve the pinned image, compiler,
   workers, native test flags and build-only scope. Bind the additional cache
   location/options to a new profile and independently validate its native event
   metadata. Do not relabel an old uncached map as compatible with this profile.
2. **Seed only the exact PR base.** Use one isolated, allowlisted push workflow
   to run the full native suite and dependency query on a passing base. Authenticate
   the source revision before and after execution. Save its map and native cache
   with identities derived from the base, toolchain, profile and reviewed producer.
   Never populate the seed from the PR head: that would give the experiment future
   knowledge. Report enrollment, seed creation and upload costs separately.
3. **Bound storage and trust.** Initially allow one cache, at most 2 GiB before
   upload; abort publication above that limit. Recheck existing usage before
   publishing, do not increase repository storage limits, and remove only this
   experiment's cache after verification. PR consumers use restore-only access,
   an exact key and no broad restore prefixes. They cannot publish a trusted seed.
   Cache directories contain build outputs, not credentials or the whole checkout.
4. **Compare real PRs.** Begin with the existing known regression, using identical
   source trees for native and Smart CI. Each gets an independent copy of the same
   base seed on a fresh runner. Native caching must remain enabled in both arms.
   Keep at most two native jobs active. Cap the seed and each comparison job at
   25 minutes; start with one seed and one regression pair, then at most one
   passing comparison pair after checking correctness. The initial pair exposed a
   setup error (workflow additions forced full scope); retain it and separately
   account for the corrected base seed and source-only comparison. This uses the second pair
   for normal passing feedback rather than extrapolating from compilation failure.
   No larger runners, AWS deployment or model calls.
5. **Verify what actually happened.** Require an authenticated cache hit and
   record native cache-hit metrics from build events, not merely cache-action
   output or repeated stdout. Reconcile all native test outcomes and every required
   build configuration. The known two compiler failures must remain visible.
   A missing cache is not a warm sample and must not be reported as one.
6. **Measure the complete path.** Use actual PR event through completed workflow,
   including cache download/restore, setup, planning, execution and uploads.
   Preserve slower attempts and report seed bytes, runner time, CPU model and
   action counts. The cold full-fallback pair received different Intel/AMD hosts
   under the same Ubuntu runner label. Record this confound; do not discard a slow
   host or claim identical hardware because the container and runner label match.
   Failure-feedback measurements are separate from passing-workload comparisons;
   a passing warm case remains necessary before claiming passing warm-CI savings.

GitHub permits PRs to restore base-branch caches and provides read-only cache
access controls. Its documented default storage allowance is 10 GB per repository;
usage beyond that can be billed. The experiment's smaller cap and usage check must
not be replaced by increasing that allowance. See [GitHub's cache reference](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching).

Expected tradeoff: native caching may already avoid most of the work Smart CI
would omit. That is a hypothesis to test, not a result. If the selected path is
slower, keep the negative result and qualify the product's useful operating range;
do not disable native caching to manufacture a speedup.

## Implemented adapter boundary

`baseline.py`, `collection_driver.py` and `execution_driver.py` accept an optional
`--native-cache` directory. It must be a canonical external directory, separate
from the repository and captures. The Docker adapter mounts it at `/native-cache`
and adds only `--disk_cache=/native-cache` to the native flags. Cached collection
and execution require `cache-profile.json`; supplying an uncached profile with a
cache, or the cached profile without a cache, is rejected. Native event validation
still checks the exact options digest; the first hosted capture has confirmed it.

`native_cache.py` fingerprints the cache after native processes finish. It rejects
links, special files, excessive nesting, more than 100,000 entries and more than
2 GiB of file content. Descriptor-relative reads do not follow links. The receipt
records file count, byte count and a content/path digest. Restored bytes must match
a receipt obtained independently from the reviewed producer; a self-declared hash
inside an untrusted cache is not authentication. Hashing and validation time belong
in the PR measurement.

`cache-seed-workflow.yml` publishes only from `codex/native-cache-base`, uses
write-only cache access, checks that repository cache usage is empty before saving,
and uploads a separate cache receipt plus the existing authenticated map evidence.
It retains the original full test command, compiler, worker policy and cleanup.
It does not execute PR source. `cache-pr-control-workflow.yml` and
`cache-pr-candidate-workflow.yml` both use read-only cache access and the exact seed
identity. A standard-library helper authenticates the approved seed workflow bytes at the
actual PR base, then validates a successful same-repository push run at that exact
SHA and approved branch, within seven days. Both arms download the receipt for
that run and attempt, bind it to the base, producer tool revision and profile, then
verify the entire restored content digest. The independent baseline does not
install the planner. Workflow files are installed on the experimental base before
seeding; a source-only PR must not modify those controls.

The candidate still discovers/authenticates its dependency map through `bazel
fetch`, using the actual base revision and `cache-publisher.json`. Its publisher
command identity is separate from local execution commands. If cache admission
fails, either workflow executes the independent uncached full suite. The candidate
also uses full fallback if planner installation fails. Native nonzero exits are
preserved. `cache-admission.json` distinguishes these cold fallback results from
valid warm samples; a passing fallback is not evidence of cache reuse.

Focused tests cover cache integrity/bounds, profile mismatch, unchanged native
failure/timeout behavior, explicit publisher configuration and the actual workflow
shell's cold-full routing for missing/invalid cache evidence. These are correctness
checks, not performance measurements. The controlled cache is separate from the
unavailable upstream private cache. No AWS deployment or model credentials are
needed.

## Verified base seed

Run `45792537512` built the passing base revision
`08f1bcddc9372a42496fea05a81f9d6b7ad6122d` with producer tool `25e32aba`.
The authenticated map contains 252 passing test targets and 324 build-only targets,
with 576 native build configurations. Its anchor matches the actual Git tree and
its profile/command digests match the reviewed cached configuration. Compatible
map reuse then avoided another native build or query. Runner policies were restored.

Workflow creation through completion took **686 seconds**, including 637.02 seconds
for the native command and 9.59 seconds for the query. This is initial enrollment,
not a PR saving. It ran on an Intel Xeon 6975P-C host with four visible processors.
The cache receipt covers **858,023,104 bytes in 7,564 files**. GitHub confirms one
base-branch cache containing **112,871,152 compressed bytes**, below the content cap.
The [seed record](../benchmarks/abseil-cache-seed-2026-11-26.json) retains identities,
hashes, native scope and the exact cache ID for cleanup.

[Native PR #22](https://github.com/SharmaKunal14/abseil-cpp/pull/22) and
[Smart CI PR #23](https://github.com/SharmaKunal14/abseil-cpp/pull/23) replay the same
known compiler regression against this seed. Their complete Git trees are identical;
both remained red on the same two real compiler failures, with zero missed native
failures. Both admitted the trusted cache and recorded 1,655 native disk-cache hits.
However, adding the consumer workflows inside these PRs correctly selected full
scope (252 tests and 324 build-only targets). Their end-to-end times were 198 and
204 seconds. Preserve this [full-fallback record](../benchmarks/abseil-cache-fallback-2026-11-26.json);
it is not evidence of subset performance. The correction moves workflows onto
the experimental base and discovers the later seed by base identity. The selector
rule for in-PR workflow changes remains unchanged.

## Corrected source-only regression

Consumer workflows now exist on the experimental base before seeding. The
standard-library discovery helper authenticates the producer at the exact PR base;
no future run ID needs to be edited into the PR. The selector's workflow-change
fallback rule is unchanged.

The corrected [seed](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45797438847)
passed all 252 native test targets and preserved 324 build-only targets. It took
967 seconds from workflow creation to completion on an Intel Xeon Platinum 8370C
host. It produced 858,019,906 raw bytes in 7,564 files and 112,954,696 compressed
cache bytes. The original experiment cache was deleted before this seed, keeping
only one cache. See the [corrected seed record](../benchmarks/abseil-cache-seed-corrected-2026-11-26.json).

[Native PR #24](https://github.com/SharmaKunal14/abseil-cpp/pull/24) and
[Smart CI PR #25](https://github.com/SharmaKunal14/abseil-cpp/pull/25) have identical
Git trees and change only the hinted-insertion header. Both admitted the exact
trusted seed. Smart CI selected the two linked-hash test targets, retained all
324 build-only targets/configurations, and caught exactly the two compiler failures
found by the complete native command. Neither selected target reached test
execution because compilation failed. Both checks correctly remain red.

Actual PR-created-to-completed-workflow times were **198 seconds native and
209 seconds Smart CI**: no saving. Native Bazel reused 363 cached test runs across
250 unaffected test targets. Both arms performed two local compile actions; the
candidate mostly removed cache lookups and internal actions. Bazel wall time fell
from 18.88 to 16.17 seconds, but the complete native command including container
startup took 167.25/165.86 seconds. Planning took 0.44 seconds; the candidate also
spent 3 seconds installing the planner and 6 seconds fetching its map. The native
control's observed container download alone took 137.62 seconds.

This is failure-feedback evidence, not passing-workload performance. Both hosts
reported the same Xeon 6975P-C model, but one pair does not establish causal or
representative performance. See the [regression record](../benchmarks/abseil-cache-regression-2026-11-26.json).

## Passing warm comparison

[Native PR #26](https://github.com/SharmaKunal14/abseil-cpp/pull/26) and
[Smart CI PR #27](https://github.com/SharmaKunal14/abseil-cpp/pull/27) add empty-node
hinted-insertion coverage to an existing test file. Their complete Git trees are
identical. No tests, worker settings or build targets were removed. Both workflows
passed; Smart CI selected the linked-hash-set target and preserved all 324 native
build-only targets/configurations. The changed target genuinely executed in both
arms: each has one uncached native test run. The full command reused 364 cached
runs across the other 251 test targets. Counts describe native runs/targets, not
individual C++ test cases.

Actual PR-created-to-completed-workflow times were **289 seconds native and
307 seconds Smart CI**, 18 seconds slower for Smart CI. Both arms performed three
local native actions. The control ran on an AMD EPYC 9V45 and the candidate on an
AMD EPYC 7763, so the exact 18-second difference is not a clean causal estimate.
Nevertheless, this pair demonstrates no end-to-end saving and no reduction in
local native action count. Planning took 0.70 seconds, map retrieval 6 seconds,
and the complete native commands took 262.18/274.41 seconds. The control's observed
container download took 230.20 seconds. See the
[passing record](../benchmarks/abseil-cache-passing-2026-11-26.json).

## Interpretation and verification

This controlled cache experiment verifies cache admission, automatic seed discovery,
source-only subset execution and preservation of the known regression. It does
**not** demonstrate warm-CI savings. Native Bazel already avoids the unchanged
work; selecting fewer targets mostly removed cached lookups, while adding planner
installation, evidence retrieval and validation. This does not invalidate the
observed cold results, but those cannot be sold as savings over an effective
native cache. One regression and one test-coverage change are not a representative
production distribution or a universal safety proof. Keep this profile experimental
and prefer native cached execution unless a broader controlled measurement shows
benefit; do not disable caching to manufacture one.

The seed used for the corrected comparisons cost 967 seconds. The discarded setup
also cost an earlier 686-second seed and a full-fallback pair; those records remain
linked above. Only one experiment cache existed at a time. Both experiment caches
were explicitly removed after their consumers completed; no storage allowance was
increased. See [cleanup and aggregate native runner usage](../benchmarks/abseil-cache-cleanup-2026-11-26.json).

To verify the completed GitHub evidence without running local benchmarks:

1. Open PRs #24/#25 and their completed checks. Both are intentionally red on the
   same hinted-insertion compiler defect. Open PRs #26/#27; both checks are green.
2. Download the run artifacts from each Actions summary. Native artifacts are
   `independent-native-1`; Smart CI artifacts are `automatic-native-1`.
3. Check `cache-admission.json` (`warm_sample: true`) and `cache-seed-run.json`
   (run `45797438847`, attempt 1). The verified cache fingerprint must match the
   separate seed receipt. A cache-action success alone does not establish this.
4. In candidate `native-pr/execution/plan.json`, verify `mode: subset`, empty
   `fallback`, selected targets (two for #25, one for #27) and all 324 `build_only`
   entries. In `execution.json` and `native.bep.json`, verify native exits and the
   matching test/build configuration scope. The records above retain artifact
   hashes and exact source/tool revisions.
5. Compare each PR's actual `created_at` with its completed workflow `updatedAt`.
   The JSON records also contain job/step times and CPUs; do not substitute only
   test time for end-to-end latency.

Artifacts have seven-day retention. The cache cleanup is intentional: reopening
these PRs now would take the cold full fallback unless a new reviewed seed is
created. Inspect the saved runs to verify these results; do not label a later
cache miss as a warm replay. All PRs remain unmerged. No AWS deployment or model
calls were made during this cache experiment.
