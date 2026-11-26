# Native cache comparison: next verification step

Status: cache adapter, bounded seed and consumer workflows implemented. The
consumer revision passed [854 hosted safety tests and builds](https://github.com/SharmaKunal14/smart-ci/actions/runs/45793248434).
The [seed run](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45792537512)
passed, and the first real regression PR pair is running. No warm-cache speed
result is claimed yet.
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
   passing comparison pair after checking correctness. This uses the second pair
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
identity. They independently download a receipt from one reviewed seed run, bind
it to the actual PR base, producer tool revision and profile bytes, then verify
the entire restored content digest. The one reviewed seed-run reference is an
experiment control, not a new requirement for ordinary map discovery.

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
both should stay red on the two real compiler failures. Cache admission and native
cache-hit evidence must pass before their timing can be classified as warm.
