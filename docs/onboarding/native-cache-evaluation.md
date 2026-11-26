# Native cache comparison: next verification step

Status: design and storage preflight only; no warm-cache benchmark has run.
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
   25 minutes; start with one seed and one pair, then at most one repeat after
   checking correctness. No larger runners, AWS deployment or model calls.
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
