# Deterministic changed-code coverage reporting

Smart CI now reports gaps for developers to address. It does not generate or
repair tests. All model campaigns remain disabled; earlier approvals are not
reused. The [generation and repair experiment](generated-test-experiment.md)
retains its original proposals, revisions and negative GitHub results.

The flow is: PR change → deterministic selection with existing fallback → native
tests → coverage-gap report. Reporting never changes the plan or authorizes an
omission. Developers must decide which behavioral assertions and test inputs are
appropriate. Full execution cannot validate behavior that it never exercises.

## What the report establishes

`smartci coverage-gaps` intersects changed **head-revision lines** with executable
line records in coverage.py/Cobertura XML. A line is flagged only when that exact
revision and environment have a reconciled execution receipt and the XML records
zero hits. Function declarations alone do not count as execution of their bodies.

The report says **no observed execution in this recorded run**, not “no test
exists.” It retains the repository, base/head commits, environment digest, GitHub
run link, execution scope, native exit status, case count and coverage hash.
Executed lines are not proof of useful assertions or comprehensive test inputs.

Missing artifacts, a different revision, a different environment, incomplete
execution, an altered hash and malformed XML have distinct evidence statuses.
Missing files, excluded/non-executable lines and deleted lines are not converted
to zero-hit findings. This initial report does not map deleted lines to historical
coverage or synthesize branch coverage from line hits.

## Trust boundary

The strict `smartci.coverage-receipt.v1` receipt is supplied by the trusted runner,
not by a PR author claiming that their coverage is valid. The CLI checks bindings
and bounded XML, but does not independently authenticate GitHub or its publisher.
Hashes are integrity checks, not signatures. Do not promote arbitrary uploaded
receipts into trusted baseline evidence.

The Textual adapter checks the clean exact Git revision, records the native
installed environment, and reconciles actual JUnit identities against native
collection using that installed pytest's JUnit naming. An unfinished or partial
test process cannot produce a reconciled receipt. The separate comparison tool
checks GitHub API run/job/PR metadata, native control parity and artifact bindings,
then reproduces the report from those artifacts. The report is advisory even when
all these checks pass.

## Usage

Run in an environment with Smart CI installed, using the receipt and profile
produced by the trusted runner:

```sh
smartci coverage-gaps \
  --repo /path/to/checkout --repository owner/repo \
  --base FULL_BASE_SHA --head FULL_HEAD_SHA \
  --environment /path/to/profile.json \
  --receipt /path/to/coverage-receipt.json \
  --coverage /path/to/coverage.xml \
  --output /path/to/coverage-gaps.json --audit /path/to/coverage-gaps.md
```

Omitting receipt/coverage produces an explicit missing-evidence report. Invalid
receipt syntax or output publication errors return exit code 2 with a redacted
error. A valid advisory report returns 0, including when it identifies gaps; it
must never replace the native test exit status or the selector's full fallback.
Identical inputs produce identical report JSON/digest. Markdown escapes input.

## Bounded GitHub evaluation

Use `examples/textual/coverage-workflow.yml` on the fork, pinned to a reviewed
Smart CI commit. Each PR runs `native` and `smart` on separate identical runner
profiles. The native command, coverage options, tests and lockfile remain
unchanged. The smart path performs existing automatic base/head discovery,
repeats planning to check determinism, preserves the production policy and full
fallback, executes the selected/native command, then reports gaps.

The two scenarios are the existing historical Markdown regression and the
separately identified artificial `_update_rows` mutation. The latter is a
coverage-gap control, not a claim of a real upstream bug. No test is generated or
edited to fit selection. Do not classify a passing full suite as validation of
the uncovered mutation.

Save the named job artifacts plus GitHub's `run.json`, `jobs.json` and
`subject-pr.json`. Reconcile them with:

```sh
uv run python examples/textual/compare_coverage_pair.py \
  --artifacts /path/to/downloaded-pair --repo /path/to/checkout \
  --output /path/to/new-comparison.json
```

Report workflow-trigger-to-job completion (including setup, discovery, planning,
tests and reporting), actual executed cases, missed native failures and total
validation-workflow/runner time. A reduced list alone is not a performance result.
The native control is evaluation overhead; the production policy itself decides
whether full execution is required. Textual's unresolved graph currently requires
full fallback. A faster full run caused by runner variation is not evidence that
test selection saved time. The completed results below use only GitHub timings.

## Completed GitHub results — 27 November 2026

Coverage reporting works on the corrected PR runs. **Production selection did
not save time.** Each arm executed all 251 files / 3,467 native case outcomes;
the 14 unresolved dependency gaps retained `INCOMPLETE_EVIDENCE` full fallback.
The tests, native command and lockfile were unchanged within and between the
initial and corrected comparisons. The tool pin was
`12324ce9502b75a514bb598993ef0941a029ef8c`.

| Real PR and run | Native trigger → result | Smart CI trigger → result | Outcome |
| --- | ---: | ---: | --- |
| [#17 historical regression](https://github.com/SharmaKunal14/textual/pull/17), [run](https://github.com/SharmaKunal14/textual/actions/runs/45935882128) | 368 s | 393 s | 25 s slower; both catch the same one failure |
| [#18 artificial uncovered change](https://github.com/SharmaKunal14/textual/pull/18), [run](https://github.com/SharmaKunal14/textual/actions/runs/45935883746) | 360 s | 397 s | 37 s slower; both pass, changed line has zero observed execution |

Every selected outcome matched its full control, with zero missed **observed**
failures and zero omitted cases. The regression is
`test_markdown_stream_switch_theme`; its red checks are expected evidence, not a
reporting failure. On PR #18, the validated report flags
`src/textual/widgets/_markdown.py:695` in `_update_rows` and asks the developer to
add behavioral tests. Its full-suite pass does not validate that unexecuted
behavior. The regression's changed measured lines 938 and 943 were executed;
line 701 has no executable line record and is not labeled measured zero.

Smart CI spent 36.27 / 36.11 seconds collecting base/head maps and planning, then
299.97 / 300.55 seconds executing the full suite. Reporting took 0.43 seconds in
each run. Native test commands took 316.44 / 309.59 seconds; that independent
runner variation is not selection benefit. The timings above include queue,
checkout, dependency/tool installation, planning, tests, reporting and artifact
upload. They start at workflow creation, not an inferred PR event-delivery time.
Whole comparison workflows took 393 / 397 seconds and together consumed 1,505
runner seconds because both arms ran for validation. Separate tool checks and
operator time are excluded.

The initial [regression run](https://github.com/SharmaKunal14/textual/actions/runs/45934838943)
and [uncovered-change run](https://github.com/SharmaKunal14/textual/actions/runs/45934847514)
are retained. Their native/Smart CI times were 371/411 and 365/414 seconds, but
report verification failed: the adapter expected `native_case_count` where the
collector publishes `cases`. It emitted missing evidence, not fabricated zero
coverage. The one-field correction and corresponding test were verified against
both original artifact sets before repeating the same source changes on GitHub.
Those initial comparisons consumed another 1,551 runner seconds.

The [durable result record](../benchmarks/textual-coverage-report-2026-11-27.json)
contains commits, environment, job links, artifact hashes, timing breakdowns,
dependency gaps and both original and corrected outcomes. The exact benchmark
tool commit passed [hosted checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/45935777337).
One pair per scenario is insufficient for a representative average. No production
subset, selection speedup or added behavioral test coverage is claimed.

### Verify the published result

1. Open each run above. Inspect `native` and `smart`; PR #17 must remain red in
   both for the same regression, while PR #18 is green in both.
2. Open the `smart` job summary and its `textual-smart-1` artifact. Confirm
   `coverage-gaps.json` has `evidence_status: validated_receipt`, the exact PR head
   and environment, and `selection_changed: false`. PR #18 must flag line 695.
3. Compare `selection.json`, `execution.json` and `junit.xml`. Both smart runs
   require full execution, select 251 files and report all 3,467 case outcomes.
   Compare job timestamps, not only pytest's duration or a count of selected tests.
4. To reproduce the strict artifact reconciliation, download either run into a
   fresh directory and save its metadata (example for PR #18):

   ```sh
   gh run download 45935883746 --repo SharmaKunal14/textual --dir /tmp/textual-gap-check
   gh api repos/SharmaKunal14/textual/actions/runs/45935883746 > /tmp/textual-gap-check/run.json
   gh api 'repos/SharmaKunal14/textual/actions/runs/45935883746/attempts/1/jobs?per_page=100' > /tmp/textual-gap-check/jobs.json
   gh api repos/SharmaKunal14/textual/pulls/18 > /tmp/textual-gap-check/subject-pr.json
   uv run python examples/textual/compare_coverage_pair.py \
     --artifacts /tmp/textual-gap-check --repo /path/to/textual-checkout \
     --output /tmp/textual-gap-comparison.json
   ```

   The checkout must contain the recorded base/head Git objects. The output path
   must not exist. If the PR advances, use the saved subject metadata bound to the
   old run; current metadata should correctly fail revision validation. GitHub
   artifacts have 14-day retention; the durable record retains findings/hashes,
   not a replacement for expired original artifacts.

No AWS deployment, model credentials or merges are needed. The safety checks are
`make check` and `uv build`; they establish code behavior, not benchmark savings.
