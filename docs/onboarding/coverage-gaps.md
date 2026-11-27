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
test selection saved time. Live results are pending; no local timing is a result.

No AWS deployment, model credentials or merges are needed. The safety checks are
`make check` and `uv build`; they establish code behavior, not benchmark savings.
