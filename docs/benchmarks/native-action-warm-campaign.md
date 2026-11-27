# Published Action evaluation with a working native cache

Predeclared on 27 November 2026, before running this campaign. Performance data
must come from real GitHub PRs. No selector or published Action changes, model
calls, merges, AWS resources, paid runner settings or storage-limit increases.

## First gate and fixed scope

Use published Action commit `e780aeb00eb5b81c35b062c65734067c03279754`, CLI
`0.2.0a2`, and its existing reviewed Abseil GCC/C++17 fastbuild disk-cache profile.
The existing full configuration interface accepts that cached profile; the bundled
short preset remains the uncached profile. Keep native tests, workers, pinned image,
flags and crash-processing safeguards equal between arms. The unchanged native
full command already uses Bazel's affected-work reuse through its cache: do not
disable cached test results or invent a slower baseline.

First enroll one passing base on isolated branch `codex/action-warm-base`. The
same published Action executes full enrollment with the existing cache adapter.
Authenticate the successful push producer, exact base, workflow, tool/profile and
cache fingerprint before each consumer. Both arms independently restore the same
base-only seed. Use restore-only service permissions on PRs, no restore prefixes,
no PR cache publication, and no sharing of PR-head outputs between arms. A missing
or invalid seed invokes the independent cold full path and is reported as cold.
Map failure still reconstructs or runs full. Native failures remain failures.

The first source change is exactly the earlier cold Action comparison's refactor
in `absl/container/internal/raw_linked_hash_set.h`: name the hinted-node insertion
result before returning `.position` (source delta from commit
`cccc702e657422a0dad864752bb103a2b188a782`). Existing tests stay unchanged. Create
three fresh PR pairs sharing the same base/head commits, with independent runners
and restored seeds. Run one pair, inspect validity/outcomes/cache hits, then finish
the three-pair warm gate. Alternate which arm is opened first. Keep every attempt,
including slower, failed or invalid/setup-error attempts; never replace them with
a favorable retry. Do not change the source case after observing timing.

Before expanding, require valid cache use, native outcome parity and a positive
median complete-PR saving, with at least two of three pairs faster. Hardware and
native work metrics still qualify that result; three noisy samples are not a
causal estimate. If warm results are negative or inconclusive, report and diagnose
them before spending compute on other scenarios, base refreshes or another repo.
Prior warm CLI results (198/209 and 289/307 seconds native/Smart) stay in the record.

## Predeclared broader cases, conditional on that gate

This is a small stratified set of change mechanisms, not a statistically
representative enterprise PR distribution. Test sources are not weakened to help
the selector. Target counts describe Bazel targets, not individual C++ cases.

| Case | Fixed change | Required evidence |
| --- | --- | --- |
| Isolated implementation | The hinted-node insertion refactor above | Genuine native cache hits, same outcomes, full end-to-end timing; three pairs first |
| Shared dependency | Replay the shared-hash implementation delta from `5d30e9bb3f397dcbe82b5ac685bf5a86328ee16f` in `hash.cc`/`hash.h` | Transitive/broad scope, retained build-only targets, all outcomes; no favorable narrowing |
| Test-only | Empty-node hinted-insertion assertions in the existing linked-hash-set test, delta `26bd456b98b698a36621698c7aa680a7818b21f4` | New assertions genuinely execute in both arms; no test settings changed |
| Build/inventory change | Add the native empty-node insertion test target, delta `2a64a2d20ecad26feabf231995aa7247735967ba` | Full fallback discovers the new current target; no old-map inventory truncation |
| Behavioral regression | In `emplace_hint`, swap `Policy::kIsMap ? list_.cend() : hint` to `Policy::kIsMap ? hint : list_.cend()` | Existing `HintedEmplaceMoveable`/`HintedEmplaceReference` assertions should detect incorrect order; verify actual behavioral failures rather than assuming them |
| Known compiler regression | Restore `.first` instead of `.position` in hinted-node insertion | Preserve the same linked-hash compiler failures as the full control; distinguish compilation failure from executed test cases |

If expansion is justified, use about three paired attempts for each selected
scenario, one scenario at a time. Advance an isolated base branch to already
evaluated passing code without merging PRs; regenerate/authenticate maps and a
base-only cache seed before successive PRs. Never relabel an old map as the new
base. Record actual enrollment/refresh runs, cache identities, source revisions,
transfers, storage and all runner usage. Do not claim calculated break-even as
observed amortization. A second supported repository is conditional on a useful
operating range here, with the same Action and no selector exemptions.

## Cost, validity and reporting bounds

- Initial gate: one seed and six PR jobs; at most two native jobs concurrently,
  25-minute job timeouts, one cache at a time, at most 2 GiB of raw cache contents
  and 100,000 entries using the existing fingerprint validator. Native commands
  retain their bounded timeouts. No automatic unbounded retries.
- The repository is public. Before this campaign, GitHub reported zero cache
  entries and zero bytes. Check again before save, retain exact cache IDs and
  compressed sizes, and delete only this campaign's cache after consumers finish.
  Do not delete unrelated data or increase storage/runner allowances. Artifacts
  retain seven days. The one-seed/six-job timeout ceiling is 175 runner-minutes;
  actual usage and transfer/storage volumes must be reported, not this ceiling
  represented as an estimate.
- Cache success means both receipt/content authentication **and** actual Bazel
  cache-hit/test-result evidence. Restore success alone is insufficient. Keep
  cold/invalid samples in the account, outside a claimed warm median.
- For every first-attempt PR, measure `PR.created_at` to terminal workflow
  `updated_at`; also record workflow-created, job and step durations. Include
  queue, checkouts, cache restore/validation, Action/CLI setup, map admission,
  planning, native execution, reporting, uploads and cleanup. Preserve CPU model,
  visible CPU count, cache hit/miss metrics and native local action counts.
- Reconcile complete native events, options, target/configuration scope and exact
  failures against the independent full control. Record selection/fallback counts,
  missing failures and native cache reuse. A passing pair cannot estimate recall;
  a few defects cannot establish universal safety.
- Report all paired timings, paired differences, median/range and aggregate job
  seconds. Charge additional full enrollment/map work separately from native cache
  seeding needed by both approaches. Where the combined seed cannot attribute an
  increment precisely, state that and report a conservative combined-cost view.

Service-level cache permissions follow [GitHub's cache-mode documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#cache-mode).
The existing cap remains below the [documented included cache storage](https://docs.github.com/en/actions/reference/limits).
The disk cache includes native build/test reuse; see [Bazel cache diagnostics](https://docs.bazel.build/versions/main/remote-execution-caching-debug.html).
