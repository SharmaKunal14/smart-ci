# Textual compatibility and GitHub experiment

This experiment evaluates the existing Python collector on Textual without
relaxing its safety rules. A long test suite is an opportunity, not proof that
the collector can safely select a useful subset.

## Scope and reproducibility

- Upstream source: `Textualize/textual` at
  `5e5b7ef58b8c5572c13a3ff9027d756623661495` (8.2.8).
- Fork: https://github.com/SharmaKunal14/textual
- Experiment base: `codex/smartci-base`; upstream `main` is unchanged.
- Existing Smart CI runtime: `fa7cb1994b98f0c2ddd0e83dd603eb9d127f6f41`.
- Ubuntu 24.04, Python 3.14, Poetry 1.7.1, upstream lockfile and syntax extras.
- Preserve upstream pytest verbosity, coverage and native plugins. Add JUnit
  output for independently comparing case identities and failures.
- Both paths run on separate GitHub-hosted runners. No artificial delays,
  altered worker settings, disabled coverage or hand-authored dependency edges.
- This is one native platform profile, not the full upstream OS/Python matrix.

The experiment branch removes inherited workflows and contains one PR workflow
with two jobs, a 20-minute job limit and seven-day artifact retention. Jobs have
read-only repository permissions and checkout credentials are not persisted.
No AWS infrastructure, paid model calls or PR merges are involved.

## Compatibility and safety

The Python collector discovers native test files twice, analyzes base and head
source, and produces deterministic plans using both revisions' dependencies.
The benchmark validates that repeating planning over the same evidence produces
the same report. This is not a claim that repeated native discovery across
different environments is always identical.

Textual contains computed imports, attribute hooks, runtime-loaded applications,
resources and snapshot/async pytest plugins. These are not automatically safe
to omit. The experiment does not add plugin allowlist entries, suppress collector
gaps or replace unknown relationships with manually chosen tests.

Missing maps are rebuilt during the PR. Incomplete maps, collection errors,
timeouts and invalid targets execute the independent native full-suite command.
A test failure stays a job failure. Native skipped/expected-failure cases remain
visible; full fallback does not claim those cases executed successfully.

The planner runs in a separate environment with its locked dependencies. Only
the observer package is installed, without dependencies, into Textual's native
environment. This avoids silently upgrading Textual dependencies to satisfy
Smart CI. Poetry explicitly selects the measured Python interpreter and asserts
its minor version before either benchmark path starts.

## Scenarios

1. Baseline: no application or test changes.
2. Localized Markdown change: reverse production code from upstream fix
   `35452692c46be734b4332dcd02bd187407756a0c`. Existing tests are unchanged.
3. Shared terminal-input parser: restore the old regex from upstream fix
   `508dbbd2a619938c7c3b17e4129b4d612f1b7f25`. Retain subsequent refactors and
   existing tests, including the upstream multi-key regression test.

Historical regressions establish realistic failure scenarios. A green native
result means this profile did not expose that regression; it must not be reported
as a caught defect. Expected regression failures must remain red.

## Verification and measurements

Open each PR's **Checks**, then the `Textual Smart CI experiment` run. Inspect
the `native` and `smart` jobs and download their `textual-*` artifacts:

- `execution.json`: commits, full/subset execution, planning/test/command times
  and the real test process exit code.
- `base-compatibility.json` and `head-compatibility.json`, when collection
  succeeds: native inventory counts, loaded plugins, gaps and evidence digests.
- `selection.json`: deterministic decision, reasons and fallback codes.
- `junit.xml`: independent case outcomes, including failures and skips.

End-to-end feedback time is workflow creation to completion of each job. Job
duration is reported separately. Both include setup, installs, planning,
execution and artifact publication; no setup is subtracted from the Smart CI
result. Native and Smart CI use the same PR head for each comparison.

The whole two-job experiment completes when the slower job completes. This is
distinct from the hypothetical feedback time if only one path were installed.
If every plan falls back to full execution, there is no test-selection benefit;
runner variation must not be described as a speedup. Benchmark repeat runs only
when they can resolve an actual performance uncertainty.

## Deployment

No AWS deployment is needed. The fork's isolated experiment branches contain
the complete workflow and `.smartci/benchmark.py`. Do not merge deliberately
regressed source into a production branch. Close the experiment PRs when done,
or reopen one to repeat its bounded GitHub run.

Hosted results are recorded separately after checking job logs and artifacts.
