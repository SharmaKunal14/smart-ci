# Fixture scopes and lower-overhead runtime observation

The previous Textual experiment attributed collection and fixture setup to every
test. This opt-in extension separates temporal scopes so that a function fixture
used by the parser tests can be distinguished from a session fixture. It remains
advisory: scope does not establish exclusive ownership of side effects, and no
runtime report is accepted as a production selection plan.

## What changed

- Public pytest collection and fixture-setup wrappers record the active scope.
  Function, class and module scopes retain a tracked test-file owner; package
  fixtures retain their package and session fixtures retain the whole session.
  Cached fixtures are never assigned only to the first consuming test.
- The observer does not request, wrap, reorder or finalize application fixtures.
  Teardown and unknown owners remain shared. Background work and cross-test side
  effects remain unproven; temporal attribution is not dependency completeness.
- An optional Python monitoring engine records starts, resumptions and generator
  throws. It reserves only a free tool ID, retains native coverage/profiling tools,
  never calls the global `restart_events`, and cleans up only its own ID. Missing
  slots or replaced instrumentation become explicit diagnostics.
- Detailed contexts use schema `smartci.runtime-observation.v2`. The original
  profile engine and v1 report remain available. Both always set `complete` and
  `omission_authorized` to false. No parameter values, exception contents, process
  arguments or external file paths are added to the report.

The APIs used are documented in [pytest's hook reference](https://docs.pytest.org/en/stable/reference/reference.html)
and [Python's monitoring reference](https://docs.python.org/3.14/library/sys.monitoring.html).

## Evaluation

The `examples/textual/benchmark.py --mode observe-scoped` path runs the same full
native tests, coverage and locked dependency environment, with these observer
options appended:

```sh
--smartci-observation-engine monitoring --smartci-observation-contexts
```

It does not change the native control or execute a proposed subset. Compare all
case identities, outcomes and skips in the two GitHub JUnit artifacts before
interpreting observations. Compare whole-job and trigger-to-result time, including
observer installation and artifact publication. Do not present observer speed as
selective-CI savings.

The assessment accepts both report versions, validates their digests and source
revisions, and expands recorded scopes conservatively. Unknown metadata expands
to every test file. Even a narrower candidate list is not an executable plan.

The 14 static gaps, path-loaded example scope, dynamic resources, plugin behavior
and external/background execution still require supported contracts before the
production selector can omit tests. This extension does not waive any of them.

## Hosted result

[Textual PR #7](https://github.com/SharmaKunal14/textual/pull/7),
[run 45043961511](https://github.com/SharmaKunal14/textual/actions/runs/45043961511),
tested head `8d41e6a879ba704f3c53633cefeaf809aa76996d` with observer pin
`20989eeeb91134ab68873bf98745f3c639ee3a09`. The observed source-file hash matches
that pin. Both jobs retained the same historical parser regex defect. Every one
of the 3,467 case identities, outcomes and skip details matched; red checks are
the real regression result, not something the evaluator changes to green.

| GitHub measurement | Native full suite | Scoped monitoring, full suite |
|---|---:|---:|
| Workflow creation to job result | 350 s (5m 50s) | 570 s (9m 30s) |
| Entire job | 347 s | 567 s |
| Native test process | 300.36 s | 509.35 s |

The two jobs consumed 914 runner-seconds in total. The observer added 220 seconds
to feedback. The previous profile-based pair added 368 seconds, but these are
single pairs on different runners and both attribution and instrumentation changed.
This does not isolate a causal engine improvement and is **not selective-CI
savings**. Both paths still executed every test.

Native coverage settings were preserved, and both reports contain the same 245
source files and 31,456 statements. Covered-line counts differ by three (27,109
native; 27,112 observed). Matching case outcomes therefore do not establish
identical execution paths; this pair does not identify the cause of that difference.

The report has 502 collection/fixture scope records, 737 executed tracked files
and the same 122 executed files outside the configured `src/` and `tests/` roots.
Parser setup is now correctly recorded under its function-scoped fixture, and
module/class initialization is recorded under the collecting test file.

Monitoring also revealed parser `__init__`, `parse`, `debug_log` and `feed`
execution in **other threads**. The first main-thread-only profile did not capture
that attribution. Assigning a long-lived worker to only its first/creating test
would be unsafe: later tests may submit work or interact with shared state.

| Candidate change | Direct test-call files | Including unresolved shared/thread activity | Authorized execution |
|---|---:|---:|---|
| `_xterm_parser.py` | 1 / 251 | 251 / 251 | Full |
| `widgets/_markdown.py` | 5 / 251 | 251 / 251 | Full |

For both subjects, the remaining main-thread `@shared` records contain **file-open
attempts, not code entries**. Coverage/report generation is one possible source,
but the report does not distinguish their origin from setup or teardown. Do not
discard them based on that hypothesis. The next bounded probe should distinguish
these phases and retained reporting/build work from actual test execution inputs.
Unknown thread ownership, external inputs and the 14 static gaps remain. No
diagnostic was waived and no candidate subset was executed.

The durable summary, input hashes, scope evidence and exact failing case are in
[`textual-scoped-runtime-2026-11-23.json`](../benchmarks/textual-scoped-runtime-2026-11-23.json).
The implementation is [Smart CI PR #8](https://github.com/SharmaKunal14/smart-ci/pull/8).
The observer commit passed 372 GitHub safety tests; the additional comparison
tool passed [387 checks plus lint, typing and package builds](https://github.com/SharmaKunal14/smart-ci/actions/runs/45044734911).
No PR is merged, and no AWS or paid model is involved.

## Reproduce the comparison from GitHub artifacts

Open the run above and inspect both full-test steps. Download the two artifacts
`textual-native-1` and `textual-observe-scoped-1`; seven-day retention applies.
The comparison tool consumes the unmodified GitHub REST run/job metadata and
those artifact directories. From a Smart CI checkout with `uv` and authenticated
`gh`, use a new verification directory:

```sh
mkdir -p /private/tmp/textual-scoped-verification
gh run download 45043961511 --repo SharmaKunal14/textual --dir /private/tmp/textual-scoped-verification
gh api repos/SharmaKunal14/textual/actions/runs/45043961511 > /private/tmp/textual-scoped-verification/run.json
gh api repos/SharmaKunal14/textual/actions/runs/45043961511/jobs > /private/tmp/textual-scoped-verification/jobs.json
uv run --frozen python examples/textual/compare_observation.py --artifacts /private/tmp/textual-scoped-verification --mode observe-scoped --output /private/tmp/textual-scoped-verification/comparison.json
```

Expected: `case_identities_outcomes_and_skips_equal: true`, no mismatched cases,
`observer_extra_feedback_seconds: 220.0`, `actual_test_omissions: 0`, and
`selective_ci_savings_demonstrated: false`. Successful **comparison** means the
outcomes match; it does not mean the deliberately regressed native tests passed.

The comparator rejects stale commits, subsets masquerading as full observations,
collection failures, duplicate/missing case identities, inconsistent suite counts,
changed skip reasons and unfinished runs. It currently accepts first-attempt PR
runs only; rerun timings need their own attempt-specific boundaries and are not
silently measured from the original trigger.
