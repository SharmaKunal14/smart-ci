# Same-VM published Action comparison: predeclaration

Declared before running this campaign. Keep the published Action
`e780aeb00eb5b81c35b062c65734067c03279754`, CLI `0.2.0a2`, reviewed Abseil
GCC/C++17 cached profile and existing native tests unchanged. No model calls,
merges, AWS work, paid runners or storage-limit increases.

## Design and scope

Separate hosted jobs cannot guarantee the same hardware. Run full control and
the published Action sequentially in **one job on one VM per real PR**. Use four
fresh PRs, all with the same base/head source revision and the earlier passing
hinted-node insertion refactor. Order is predeclared: full/Smart, Smart/full,
Smart/full, full/Smart. Start the first job, verify its evidence, then run the
remaining three, one at a time. Keep every attempt, error and slower result.

One fresh approved-branch enrollment publishes the exact-base map and native
cache. Authenticate the producer and independent receipt as in the previous
campaign. Before **each** arm, independently restore the exact base cache and
verify its full content fingerprint. Move the used cache out of the active path
before the other restore; never reuse PR-head outputs. Each native invocation
uses a fresh container/tmpfs workspace and Bazel server. Cache permissions stay
read-only in PR jobs. Full control retains native affected-work reuse.

Pull and inspect the same digest-pinned upstream compiler image before either
arm. This common setup is timed and charged, not silently excluded. Clear Linux
filesystem page/dentry/inode caches before each arm's native command using the
same bounded ephemeral-runner operation; include that operation in arm time.
Record CPU, VM boot identity hash, memory/disk availability, source revision,
cache fingerprints, image digest, execution order and native events. Run neither
arm concurrently with the other. Balance order because CPU scheduling and other
residual VM state can still vary over time.

Use the unchanged independent native full command and the actual pinned composite
Action (including installation, authenticated map retrieval, planning and its
audit upload). Full control uses a fixed system Python entrypoint so the Action's
PATH updates cannot change it in the Smart-first runs. No selection exemptions,
test changes, disabled native cache or selective-only warmed setup.

Cache admission failure takes the existing independent cold full path and makes
the matched sample invalid. Missing/invalid maps retain production reconstruction
or full fallback. Both arms are allowed to finish after a native failure so their
outcomes can be compared; the aggregate job must still fail if either arm fails
or required comparison evidence is missing. Never turn an expected test failure
into a green production result.

## Measurements and decision

Primary comparison: each arm's measured cache restore/validation, preparation,
native execution and audit-publication interval on that same VM. Report all four
paired differences, median/range, order groups, native cache hits, local actions,
actual uncached test runs, selected targets and exact outcome parity. A passing
case cannot estimate failure-detection recall. Keep earlier negative/mixed runs.

Also report actual PR-to-terminal-workflow time and total runner usage for the
**joint** benchmark, plus fresh enrollment and shared setup/cleanup. A calculated
single-arm cost can add the same measured common cost to each arm, but must be
labeled accounting, not two independently observed production PR latencies.
The two-arm joint job is an experiment and intentionally runs both approaches.
Do not infer lifecycle amortization across evolving base commits from it.

A consistent incremental benefit requires positive median saving and at least
three of four valid pairs faster, with gains in both order groups. Four samples
remain preliminary; report order effects, invalid samples and residual noise.
If that condition fails, report no demonstrated reliable incremental advantage;
do not optimize the workload or search another repository during this campaign.

Bounds: one seed job (25-minute timeout), four paired jobs (35-minute timeout),
one active native job at a time, one published cache capped at 2 GiB/100,000 entries,
seven-day artifacts. Check free disk before the pair and preserve at most two
local used-cache copies. No unbounded retries. Delete only this campaign's
published cache after all consumers finish. Record actual compute/storage; the
165-minute job-timeout sum is a ceiling, not a cost estimate.

The same-VM design follows [GitHub's job execution model](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#choosing-github-hosted-runners).
It removes the previous between-arm CPU and image-download differences, not all
sources of measurement noise or the need for broader regression validation.
