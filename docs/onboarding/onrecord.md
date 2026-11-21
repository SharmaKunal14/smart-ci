# OnRecord: scan once, then select tests on eligible PRs

This pilot adds automatic TypeScript dependency discovery and native Vitest **file-level** selection to Smart CI. Every case inside a selected file runs. It does not select individual `it(...)` cases. No manual import graph, saved baseline, AWS service or model API is required.

## Starting point and implemented behavior

The earlier native Vitest example rejected custom configurations, and the Python CI integration required a saved baseline to narrow its proposal. The new `smartci typescript` commands preserve the supported OnRecord Vitest configuration and rebuild both Git revision maps automatically. Saved map files are audit outputs; this implementation does not load them as trusted caches.

1. `scan` enumerates tracked files, obtains test files from Vitest, and resolves imports with the repository's TypeScript compiler.
2. `run --base <commit>` analyzes the PR checkout and reconstructs its Git merge base in a temporary checkout. Neither requires a previously saved map.
3. The selector follows dependencies from **both** revisions. Removed imports, deleted files and renames therefore retain their old relationships.
4. It runs affected files plus mandatory files. The audit records selected/omitted IDs; `run.json` and `audit.md` include readable file paths.
5. Missing or unsupported evidence runs the independent, unfiltered native Vitest suite. An incomplete subset retries the full suite. Observed test failures remain failures even if a retry passes.

The enrolled source revision is `cfcb957baee9a6e90b0f156f4458b33994117287` of `SharmaKunal14/slack-incidence-evidence`. `examples/onrecord/typescript.json` enrolls its two TypeScript projects. The original OnRecord checkout and its deployment workflows are not modified by local verification.

## Supported analysis and limits

- TypeScript 5, Vitest 3, a tracked package lock, and literal `vitest.config.ts` using `defineConfig({ test: ... })`. NodeNext `.js` imports are resolved to TypeScript source; static imports, re-exports and literal dynamic imports are followed.
- TypeScript project references, extended configurations, custom Vite plugins, Vitest workspaces and other unsupported configuration trigger full execution. This is an OnRecord profile, not universal TypeScript support.
- Files using opaque loaders, file access, subprocesses or other recognized indirect behavior conservatively depend on all tracked files. That deliberately increases the selection.
- Manifest/lock changes, configuration, migrations, CI files and the configured infrastructure/scripts/web/website paths require full execution. Changed JS/TS outside the enrolled compiler projects also requires full execution.
- Base and head must have identical dependency manifests before reusing installed dependencies. Otherwise Smart CI runs the full current suite. Use `npm ci --ignore-scripts` in a clean ephemeral checkout; fingerprints do not prove that `node_modules` is untampered.
- Equal source revisions, configuration, collector version and environment should produce the same canonical plan. Test-file discovery is repeated to detect instability. Timings and test results are separate from the deterministic plan digest.
- Selection depends on supported static relationships. External packages, environment-dependent behavior, reflection and unrecognized runtime coupling can defeat static analysis. This does **not** establish zero unsafe skips or production-wide regression recall.
- Native runner code is trusted repository code. Environment scrubbing removes inherited credentials and Node injection options, but is not a security sandbox. Local verification uses `--offline` on macOS to deny outbound network to Node and its children. That option fails explicitly if isolation cannot be enabled. The proposed Linux workflow has no AWS/model credentials, but does not implement a network sandbox.

## Local verification

From the Smart CI checkout:

```sh
export UV_CACHE_DIR=/private/tmp/smartci-uv-cache
uv sync --frozen
export SMARTCI_TYPESCRIPT_NODE_MODULES=/Users/kunalsharma/Fun/project/slack-rca/node_modules
make check
uv run python scripts/onrecord_pilot.py \
  --source /Users/kunalsharma/Fun/project/slack-rca --offline
uv build
```

The source checkout must already contain OnRecord's installed TypeScript/Vitest dependencies. The pilot clones the pinned source into a new directory under `demo-output/onrecord/verification-*` and **copies** dependencies, so test caches cannot modify your original checkout. It never pushes or merges. Each invocation creates new artifacts; it does not overwrite previous evidence.

Expected scenarios:

1. Initial scan and full native suite pass.
2. A harmless `src/domain/incident.ts` change runs a nonempty proper subset and passes.
3. Rebuilding both maps again produces the same plan, without loading the previous map files.
4. An intentional lifecycle-version defect fails in the subset. The independent full suite detects exactly the same failing case identities.
5. Restoring the defect and changing the dependency lockfile forces full execution and passes.

The terminal prints progress before collection, reconstruction and execution. Inspect `verification.json` for the scenario checks; each scenario has `selection.json`, `audit.md`, `run.json`, and revision maps. Exit codes are **0 passed, 1 observed test failure, 2 incomplete/tool error**. An intentional defect is an expected failure inside the harness; the harness succeeds only if it is caught.

Focused real-Node tests require `SMARTCI_TYPESCRIPT_NODE_MODULES`; without it, those integration tests are explicitly skipped. A successful default Python test run with skips is not evidence that the new native integration was exercised.

## Individual CLI commands

Use a **clean disposable checkout** with installed dependencies and full Git history. Output directories must be new and outside that checkout. Substitute your actual absolute paths and a complete base commit ID:

```sh
uv run smartci typescript scan --repo /absolute/path/to/disposable-onrecord \
  --config examples/onrecord/typescript.json --output /tmp/onrecord-initial --run-full --offline

uv run smartci typescript run --repo /absolute/path/to/disposable-onrecord \
  --config examples/onrecord/typescript.json --base BASE_COMMIT_SHA \
  --output /tmp/onrecord-pr --offline

uv run smartci explain /tmp/onrecord-pr/selection.json
```

The second command defaults to actual selective execution for eligible changes. Add `--shadow` only when you deliberately want a full-run audit. To force all tests, use the normal `node node_modules/vitest/vitest.mjs run --config vitest.config.ts` command. The CI template also supports repository variable `SMARTCI_FORCE_FULL=true`.

## GitHub enrollment, without deployment

The PR-only workflow template is `examples/onrecord/pull-request.yml.in`. It checks the GitHub PR test-merge revision, rebuilds missing maps, and runs eligible subsets. It has read-only contents permission, immutable action/tool references, no persistent checkout credentials, a timeout, concurrency cancellation and short artifact retention. It does not call the existing deployment workflow. Full execution remains independent if Smart CI installation or analysis is unavailable.

1. Review and publish this Smart CI change to a **non-main branch** of its public repository. Record the full commit SHA containing the new adapter. The old published Smart CI commit cannot run these commands.
2. Render the workflow using that real published SHA:

   ```sh
   uv run python scripts/render_onrecord_ci.py \
     --tool-repository SharmaKunal14/smart-ci \
     --tool-ref PUBLISHED_SMARTCI_COMMIT_SHA \
     --output /tmp/onrecord-smartci.yml
   ```

3. On an OnRecord feature branch, copy that file to `.github/workflows/smartci-tests.yml` and open a PR. Keep the existing deployment-bearing `ci.yml` unchanged. The workflow-addition PR itself is a broad CI change and should run the full suite.
4. To verify a subset **without merging**, open a second PR whose base is that enrollment branch, changing only eligible application source. Check that its Smart CI job reports `execution: subset`, a nonempty omission list, and matching executed files. An intentional-defect PR should fail; a lockfile-change PR should run everything.
5. Download the audit artifact and inspect the exact head/base commits, selection digest, fallback reason, executed files/cases and result. No failed job should be described as a passing workflow.

The template has now passed the two hosted pilot runs recorded below. Both pilot PRs remain open and unmerged; the workflow is not installed on OnRecord main. Nothing in this change enables AWS access, creates CloudFormation resources, merges OnRecord code or makes model calls. GitHub runner usage still consumes time; check your account's billing policy before enabling repeated runs.

## Verification recorded on 21 November 2026

The complete fresh run at `demo-output/onrecord/verification-v71l1jhg/verification.json` passed all scenarios on macOS with TypeScript 5.9.3 and Vitest 3.2.7. Node processes and their children had outbound network blocked.

| Scenario | Files executed | Cases executed | Observed result |
| --- | ---: | ---: | --- |
| Initial full verification | 103 | 440 | Passed |
| Harmless domain change | 64 | 280 | Passed, no fallback |
| Same revisions, maps rebuilt again | — | — | Identical canonical selection |
| Seeded lifecycle-version defect | 64 | 280 | Failed, as expected |
| Independent full suite with that defect | 103 | 440 | Same one failing case identity |
| Dependency lockfile change | 103 | 440 | Passed, full fallback |

The passing subset omitted 39 files and 160 cases. In that run, planning took 3.66 seconds and selected execution 15.16 seconds, or 18.92 seconds total. The independent full execution took 21.69 seconds, excluding its initial scan. These are single local observations with warm dependencies. That adapter requested two Vitest workers but disabled file parallelism, which made Vitest use one worker. They are **not** a benchmark against OnRecord's unmodified parallel `npm test`, a hosted CI speedup claim, or an AWS cost estimate.

An earlier attempt (`verification-hzl3mozu`) failed one existing `seedSlackIncident` test during the full fallback. The independent native rerun and the subsequent complete fresh pilot both passed. Its cause is unconfirmed; the failed artifact remains available and is not counted as a successful run. The adapter preserved that failure as a failing exit status.

The final `make check` passed formatting, lint, strict typing and all **199 tests**, with the native TypeScript/Vitest integration tests enabled. The workflow was rendered and its YAML parsed locally, with focused tests for immutable references, permissions, PR-only triggers and independent full fallback. Those local checks preceded the hosted verification recorded below. The wheel and source distribution built successfully, and the wheel contains the JavaScript compiler bridge.

Files changed: `src/smartci/cli.py`; new `src/smartci/typescript/{__init__.py,models.py,collector.py,inspect.mjs,native.py,commands.py}`; `schemas/typescript-{collector,snapshot}.v1.json`; `examples/onrecord/{typescript.json,pull-request.yml.in}`; `scripts/{onrecord_pilot,render_onrecord_ci}.py`; `tests/{test_typescript,test_onrecord_workflow}.py`; this guide, `README.md`, and `plan.md`. Existing plan edits were preserved. No Python-selector or existing adapter behavior was intentionally changed.


## Live GitHub verification on 21 November 2026

The first hosted runs used Smart CI runtime `e6b35ea089abedfd49b6ca0547a5351058d6b1ed`
on `codex/onrecord-typescript-selection`. The workflow pinned that immutable commit.
See the performance investigation below for the subsequent adapter revision.

| PR and run | Change | Actual execution | Result |
| --- | --- | --- | --- |
| [Enrollment PR #29](https://github.com/SharmaKunal14/slack-incidence-evidence/pull/29), [run 44887119368](https://github.com/SharmaKunal14/slack-incidence-evidence/actions/runs/44887119368) | Adds only `.github/workflows/smartci-tests.yml` | Full: 103 files / 440 cases, `RISK_PATH` | Passed |
| [Subset PR #30](https://github.com/SharmaKunal14/slack-incidence-evidence/pull/30), [run 44887147786](https://github.com/SharmaKunal14/slack-incidence-evidence/actions/runs/44887147786) | Adds only a blank line and `// Smart CI live subset verification.` to `src/domain/incident.ts` | Subset: 64 files / 280 cases, no fallback | Passed |

Both runs had one execution attempt, zero failed cases and zero skipped cases.
The downloaded reports were checked for plan digest integrity, execution-to-plan
binding, selected IDs matching executed paths, and a proper subset of the inventory.
The reported tested revisions match the PR merge commits and their expected parents:

- Enrollment: base `cfcb957baee9a6e90b0f156f4458b33994117287`, tested merge `ab39fb3f8dc20d9ed550797278b34bc761b072c7`.
- Subset: base `cb649e81b6941e0d603e9edf39925d17695e69e9`, tested merge `7c5af76178658642af95ab3f63d21171f9d0053b`.

Artifacts and the checked receipt are retained locally under
`demo-output/github/onrecord-live/`, including `verified-results.json` and each
run's `selection.json`, `run.json` and `audit.md`. GitHub artifacts have three-day
retention, so the run links and this committed record outlive their download window.

This proves automatic PR-triggered test-file reduction for this supported change.
The comment does not alter behavior and therefore does not measure regression recall.
The separate local lifecycle-version defect (`+1` changed to `+2`) was caught by
both subset and full execution; it was not introduced in either live PR.

Hosted timing does not establish savings: full planning/execution took 3.62/22.51
seconds (26.15 total); subset planning/execution took 5.53/22.41 seconds (27.96 total).
These totals exclude dependency installation and other workflow steps. Repeated,
paired measurements across representative changes are still needed.

Both PRs remained OPEN with no merge timestamp after verification. OnRecord main
remained at `cfcb957baee9a6e90b0f156f4458b33994117287`. No deployment workflow was
triggered by either pilot branch, no AWS resources were deployed, and no model
credentials or paid model calls were used. Rollback during this pilot is simply
to close the unmerged PRs; the existing main-branch CI is unchanged.

## Performance investigation and reproducible comparison

The first hosted subset was slower overall: its execution saved only 0.11 seconds,
while planning took 1.91 seconds longer. Those were different runner instances,
not a controlled benchmark. Vitest was also forced to run files serially by
`--no-file-parallelism`, despite the adapter requesting two workers. The selected
files retain several of the slower tests, and file startup, imports and isolation
cost time that individual test-body durations do not capture.

The optimization removes the serial override while retaining a two-worker limit
and Vitest's default file isolation. TypeScript import resolution now uses the
compiler's cache within one revision/configuration, and graph IDs are computed
once per file. No graph cache is reused across revisions or CI runs. The workflow
caches npm downloads by lockfile; it still runs `npm ci --ignore-scripts` to install
dependencies afresh. A cold cache is not a demonstrated installation saving.

Safety behavior is unchanged: both revision maps are rebuilt, native discovery is
repeated, opaque relationships broaden selection, uncertain evidence runs the full
suite, and missing subset results trigger full retry without erasing failures.
The regression suite includes actual parallel-file global-state isolation and
guards against `.only`, empty success, missing results and unsupported analysis.

To verify the implementation, use the local verification commands above. For a
performance comparison, prepare a clean disposable checkout of the eligible PR
with its locked dependencies installed, then clone the old Smart CI control:

```sh
git clone https://github.com/SharmaKunal14/smart-ci.git /tmp/smartci-baseline
git -C /tmp/smartci-baseline checkout --detach e6b35ea089abedfd49b6ca0547a5351058d6b1ed
uv run --frozen python scripts/benchmark_onrecord.py \
  --repo /absolute/path/to/disposable-onrecord \
  --baseline-tool /tmp/smartci-baseline --base FULL_PR_BASE_COMMIT_SHA \
  --output /tmp/onrecord-benchmark --rounds 3 --offline
```

Use new output and clone directories; substitute the repository path and complete
PR base commit. `--offline` requires macOS; it blocks outbound network from native
tests. The benchmark runs old/new planning plus subset execution and two full-suite
controls on the same checkout, rotating order across three rounds. One full control
uses two workers; the other preserves the repository's default worker settings.
It rejects fallback, retries, changed graphs/selection/reasons, changing counts,
skips or failures. Repeated plans must have identical digests within each tool
version. `summary.json` contains medians and `measurements.json` retains every
sample. Neither includes dependency installation; these are warmed checkout
measurements, not universal production savings or runner billing estimates.

The hosted equivalent is explicitly opt-in: repository variable
`SMARTCI_BENCHMARK=true` adds the same bounded experiment only to the same-repository
`codex/smartci-subset-probe` branch. The ordinary test step runs first and remains
authoritative. Remove the variable after the experiment; normal PRs then run no
benchmark controls. Keep the PRs unmerged during this pilot. No AWS deployment or
model calls are required for either verification path.

### Measured optimization result, 21 November 2026

Published runtime: `ed12285e97fa8300a2654ad2b111d68d5c3b70ca`. Both updated pilot
PRs passed and remain unmerged:

- [Enrollment run 44889100750](https://github.com/SharmaKunal14/slack-incidence-evidence/actions/runs/44889100750): 103 files / 440 cases, full execution with `RISK_PATH`, one attempt, no failures/skips. Planning plus execution: 17.84s.
- [Subset and benchmark run 44889127164](https://github.com/SharmaKunal14/slack-incidence-evidence/actions/runs/44889127164): normal execution 64 files / 280 cases, no fallback/retry/failures/skips. Planning plus execution: 13.47s. The PR still changes only a comment in `src/domain/incident.ts`.

The full suite in the first bullet is on a different runner; use the paired
benchmark below for comparisons. These are median wall seconds over three rounds
per variant, including Python startup and planning where applicable:

| Variant | Files / cases | GitHub Ubuntu, 4 CPUs | Local macOS, 8 CPUs |
| --- | ---: | ---: | ---: |
| Previous Smart CI subset | 64 / 280 | 18.89 | 19.15 |
| Optimized Smart CI subset | 64 / 280 | 13.31 | 11.95 |
| Native full suite, two workers | 103 / 440 | 15.73 | 11.13 |
| Native full suite, default workers | 103 / 440 | 13.87 | 6.85 |

The optimization reduced hosted adapter latency by 29.6%. The net advantage over
native full execution was only 0.56s (4.0%), with overlapping observed timing
ranges. On the Mac, native full execution remained faster. Three rounds of one
comment-only change provide limited performance evidence; they do not establish
general savings, billing reduction, or regression recall. Test counts alone are
not a performance metric. The native-default control uses the repository's worker
defaults; the adapter retains a fixed two-worker resource limit.

Hosted planning median decreased from 3.62s to 3.10s; subset execution from 15.22s
to 10.21s. Independent component medians need not sum to the wall median. Both
native inventories and full dependency graphs, selected IDs and reasons matched
between tool revisions. Plans repeated deterministically within each revision.

[Raw samples, medians and exact commits](../benchmarks/onrecord-2026-11-21.json)
are committed so they survive GitHub's three-day artifact retention. The hosted
subset job took 4m14s **because it included twelve explicit benchmark runs**; its
ordinary test step took approximately 14s. `SMARTCI_BENCHMARK` was removed after
completion and its absence verified. Ordinary PRs do not pay for those controls.
Both npm caches were cold and were saved successfully; cache-hit installation
savings have not been measured. Each dependency installation took about 34s.

Verification: `make check` passed formatting, lint, strict typing and **211 tests**
with native integrations enabled; `uv build --offline` passed and the wheel
contains the current compiler bridge and native runner. The fresh offline pilot
at `demo-output/onrecord/verification-ko07nz8x/verification.json` passed initial
full, subset, map repeatability, seeded-defect and lockfile fallback checks. The
seeded defect produced the same failing case identity in subset and full runs.
The rendered workflow parsed as YAML, and hosted reports passed digest/execution
binding, exact file-set and Git merge-parent checks.

Files changed in this optimization: `src/smartci/typescript/{native.py,collector.py,inspect.mjs}`;
`examples/onrecord/pull-request.yml.in`; `scripts/benchmark_onrecord.py`;
`tests/{test_typescript.py,test_onrecord_workflow.py,test_benchmark.py}`;
`README.md`, `plan.md`, this guide and the benchmark JSON. OnRecord PR #29 updates
only `.github/workflows/smartci-tests.yml`; PR #30 remains comment-only.

Separate follow-up: the existing OnRecord lockfile's npm install audit reports
20 dependency vulnerabilities (9 moderate, 9 high, 2 critical), and GitHub reports
Node 20 action-runtime deprecation warnings for existing action pins. This change
does not update dependencies or suppress those checks. These require their own
review; passing tests are not a clean dependency-security audit.
