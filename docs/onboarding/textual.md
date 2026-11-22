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

## Initial hosted baseline

[Baseline PR #1](https://github.com/SharmaKunal14/textual/pull/1),
[run 44990994247](https://github.com/SharmaKunal14/textual/actions/runs/44990994247):

| Measurement | Native | Smart CI |
|---|---:|---:|
| Workflow trigger to job completion | 365 s | 410 s |
| Entire job duration | 356 s | 402 s |
| Measured command | 301.73 s | 345.50 s |
| Planning | 0 s | 34.70 s |
| Test subprocess | 301.73 s | 310.80 s |
| Native cases | 3,467 | 3,467 |
| Executed file selection | Full | Full (251 files) |

Both paths reported 3,459 passes, three skips, four expected failures and one
non-strict unexpected pass. JUnit case identities and skip identities matched.
The seven JUnit `skipped` records include the four expected failures; they are
not seven ordinary skips. The planner returned `INCOMPLETE_EVIDENCE`, with no
omitted test files. **The observed feedback time was 45 seconds slower.**

The collector recorded 30 gaps per snapshot: two custom import paths, three
dynamic attribute hooks, two dynamic-code sites, four dynamic imports, two
unresolved external imports, four unresolved local imports, one unreviewed
plugin-set gap, one unsupported module name and eleven namespace-package gaps.
Reviewing the plugin set alone would leave 29 gaps. These are collector
limitations, not findings that Textual's source is unsafe. Some are conservative
false positives, such as an object-level read-only attribute hook. Removing gaps
without modelling their effects would invalidate the experiment.

The first launch selected Poetry's Python 3.12 interpreter and failed Smart CI
installation. It was cancelled, explicitly excluded and corrected before the
valid baseline. A superseded concurrency-cancelled run is also excluded.

This single baseline is not a statistical speed estimate. Full selection proves
there was no test omission benefit on this run; the exact timing delta also
contains ordinary hosted-runner variability.

## Completed regression results

| Real PR | Native trigger to result | Smart CI trigger to result | Smart CI slowdown | Native / Smart failures |
|---|---:|---:|---:|---:|
| [Markdown #2](https://github.com/SharmaKunal14/textual/pull/2) | 352 s | 392 s | 40 s | 1 / 1, identical |
| [Terminal parser #3](https://github.com/SharmaKunal14/textual/pull/3) | 397 s | 470 s | 73 s | 1 / 1, identical |

Hosted runs:
[Markdown 44991451218](https://github.com/SharmaKunal14/textual/actions/runs/44991451218)
and [parser 44991456809](https://github.com/SharmaKunal14/textual/actions/runs/44991456809).
Complete job durations were 350 versus 390 seconds for Markdown, and 394 versus
467 seconds for the parser. Planning consumed 35.91 and 52.54 seconds respectively.
These are individual observations on different PRs, not repeated-run medians.

Both paths collected the same 3,467 cases and retained identical skip identities.
The Markdown failure was `test_markdown_stream_switch_theme`; the parser failure
was the existing `test_extended_keys` case for the colon-separated multi-key
sequence. In each case, the exact JUnit failure identity matched, with zero
omitted or extra failures. Both PRs intentionally remain red and unmerged.

Every Smart CI plan selected all 251 files with `INCOMPLETE_EVIDENCE`. The native
commands ran independently, without retries or disabled assertions. **This
experiment failed the performance objective.** The fallback preserved the two
observed regressions; it did not demonstrate selective regression detection.

The next engineering question is whether general support for namespace packages,
runtime loaders, test resource relationships and plugin behaviour can safely
produce narrower graphs. Merely suppressing gaps or precomputing an incomplete
graph cannot establish that. Even complete file-level graphs may remain broad
because of shared initializers and framework dependencies. No speedup is promised.

Evidence: `docs/benchmarks/textual-2026-11-22.json`, computed from the downloaded
GitHub job metadata, compatibility reports, decisions, execution records and
JUnit artifacts. Raw downloads are retained under ignored `demo-output/textual/`.

The benchmark harness is in
[Smart CI PR #4](https://github.com/SharmaKunal14/smart-ci/pull/4).
[GitHub safety run 44991110872](https://github.com/SharmaKunal14/smart-ci/actions/runs/44991110872)
passed all 296 tests, formatting, lint, typing and distribution build. The source
collector and selection implementation were not modified for this experiment.
