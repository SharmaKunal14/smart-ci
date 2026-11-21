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

The template has local validation, not a completed hosted Actions run. Publishing the tool and opening these PRs are separate enrollment steps. Nothing in this change enables AWS access, creates CloudFormation resources, merges OnRecord code or makes model calls. GitHub runner usage still consumes time; check your account's billing policy before enabling repeated runs.

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

The passing subset omitted 39 files and 160 cases. In that run, planning took 3.66 seconds and selected execution 15.16 seconds, or 18.92 seconds total. The independent full execution took 21.69 seconds, excluding its initial scan. These are single local observations with warm dependencies. Both use a maximum of two Vitest workers and disable file parallelism for bounded execution. They are **not** a benchmark against OnRecord's unmodified parallel `npm test`, a hosted CI speedup claim, or an AWS cost estimate.

An earlier attempt (`verification-hzl3mozu`) failed one existing `seedSlackIncident` test during the full fallback. The independent native rerun and the subsequent complete fresh pilot both passed. Its cause is unconfirmed; the failed artifact remains available and is not counted as a successful run. The adapter preserved that failure as a failing exit status.

The final `make check` passed formatting, lint, strict typing and all **199 tests**, with the native TypeScript/Vitest integration tests enabled. The workflow was rendered and its YAML parsed locally, with focused tests for immutable references, permissions, PR-only triggers and independent full fallback. No hosted OnRecord workflow run was performed. The wheel and source distribution built successfully, and the wheel contains the JavaScript compiler bridge.

Files changed: `src/smartci/cli.py`; new `src/smartci/typescript/{__init__.py,models.py,collector.py,inspect.mjs,native.py,commands.py}`; `schemas/typescript-{collector,snapshot}.v1.json`; `examples/onrecord/{typescript.json,pull-request.yml.in}`; `scripts/{onrecord_pilot,render_onrecord_ci}.py`; `tests/{test_typescript,test_onrecord_workflow}.py`; this guide, `README.md`, and `plan.md`. Existing plan edits were preserved. No Python-selector or existing adapter behavior was intentionally changed.
