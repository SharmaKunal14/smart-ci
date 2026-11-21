# Phase 5: deterministic shadow CI

Phase 4 supplied local Python discovery and deterministic selection. Phase 5 adds
run identity, protected-baseline retrieval/publication, a shadow comparison, a
reviewable GitHub Actions enrollment, and visible progress before long pilot steps.
No AWS service or model is involved. This is a Python/pytest pilot, not automatic
support for every language or repository.

## What happens on a PR

1. GitHub triggers the existing `Test` workflow on PR creation, synchronization
   (including force-push), reopening and reruns. There are no path exclusions.
2. An isolated lookup job runs pinned Smart CI code, checks the protected default
   branch and looks for a successful push run at the PR's exact base SHA. It
   validates workflow/repository/run/attempt, artifact digest, payload identity,
   policy digest and expiry. It executes no application code. Missing evidence
   means full fallback; a PR artifact cannot become a baseline.
3. The native job checks out `github.sha`: for the ordinary PR event this is the
   tested merge commit, not merely the contributor's head. Context records both,
   along with the base SHA, run ID and attempt. Full Git history supports the diff.
4. Smart CI discovers the tested revision's dependencies and test files. It
   validates base/head compatibility, computes a deterministic proposal, and saves
   the proposal artifact **before** reading full execution results.
5. The native full command runs once, whether analysis succeeds, fails, times out
   or is disabled. Its exit status and coverage gate remain authoritative. Shadow
   planning never passes selected IDs to this command.
6. Comparison reconciles native case IDs, plugins, outcomes, revision and proposal
   digest, and reports any failing test file omitted by the proposal. Only a
   complete, successful, skip-free Linux/CPython 3.14 protected default-branch push
   can publish a seven-day baseline in a separate control job. No PR publishes one.

The enrollment replaces only the existing Ubuntu/Python 3.14 matrix cell. Other
platform/version cells, musl, property and downstream jobs remain intact. The new
cell executes the upstream Nox session's inner dependency installation, editable
installation, coverage/pytest and coverage-report commands directly. It does not
invoke Nox again. Equivalence of the generated job on GitHub still needs live
verification. Native dependencies follow upstream's test group; dependency drift
can invalidate baseline compatibility and increase full fallbacks.

## Platform skips

The observer records exact skip reasons. A separate local shadow policy recognizes
only `tests/test_manylinux.py::test_is_manylinux_compatible_old` on Darwin, with
reason `requires a glibc-based Linux` and the reviewed source-file SHA256 from the
pinned packaging revision. A changed source, reason, case, platform or an xfail
does not match this exception.

On macOS the comparison may therefore say `complete_with_expected_skips`, meaning
the observed behavior reconciles with the reviewed profile. It is **not** complete
coverage and is **never** eligible for baseline publication. The original runner
contract still reports a skipped suite as `incomplete`. Linux CI has no permitted
skips; a skip there prevents baseline publication. We have not removed or forced
the upstream test to run on an incompatible platform.

## Local verification

Run from the Smart CI project, with the Phase 4 disposable pilot already set up:

```sh
export UV_CACHE_DIR=/private/tmp/smartci-uv-cache
uv sync --frozen
make check
uv build
uv pip install --python demo-output/onboarding/packaging/environment/bin/python \
  --no-deps --reinstall dist/smartci-0.1.0-py3-none-any.whl
make shadow-demo
make onboarding-demo
```

If the managed pilot is absent, run `make onboarding-setup` once before refreshing
its observer. It downloads public dependencies. Do not run the two demos
concurrently: the onboarding demo changes revisions in the disposable checkout.
Rebuild/reinstall the observer after Smart CI source changes; implementation hashes
are intentionally part of evidence compatibility.

`make check` runs formatting, linting, strict typing and tests. Shadow tests include
artifact tampering, expiry, wrong producer/revision, missing/duplicate results,
unexpected skips, native failures, force-full, collector failure, repeatability,
and real Git/import discovery through the PR preparation path. Linux promotion
inputs in unit tests are simulated; they are not evidence of a real Linux CI run.
Workflow tests execute the native shell block with controlled failing/successful
commands and verify that observer failure cannot swallow the native exit code.

`make shadow-demo` prints collection progress, creates two identical proposals,
then executes the full native pytest suite once. Expect a full fallback because
there is no trusted GitHub baseline locally, then an explained Darwin skip or a
complete Linux result. The local run is deliberately not publication-eligible.
Inspect the printed `demo-output/shadow/<run>/` directory: `plan-1/selection.json`,
`plan-2/selection.json`, `comparison.json`, `native.json` and `native.log`.

`make onboarding-demo` rechecks all nine Phase 4 changes against full native test
results. It now prints before baseline execution, each discovery, each full run,
and snapshot repeatability checks. It still takes several minutes because it
intentionally repeats the full suite for different experimental revisions. Each
ordinary CI job runs its suite once; this multi-scenario acceptance harness is
different.

## Enrolling a GitHub repository

Nothing has been pushed or enabled remotely. This checkout has no Git remote. A
GitHub destination and usable authentication are prerequisites for live checks.
PyPI can distribute the Smart CI package later; GitHub hosts the repositories,
PRs and Actions. A fork of `pypa/packaging` is appropriate because we cannot install
workflows or branch protections in the upstream project without maintainer access.

1. Publish the reviewed Smart CI project to a repository you control. Record its
   full 40-character commit SHA; do not use a mutable branch/tag. A public tool
   repository avoids adding cross-repository credentials to the PR job. Private
   distribution needs a separately reviewed access design and is not implemented.
2. Use a packaging fork containing the reviewed workflow from commit
   `929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5`. The generator checks the original
   workflow's SHA256 and refuses drift. Replace the values below with your actual
   published tool repository and commit:

   ```sh
   uv run python scripts/render_ci.py \
     --repo /absolute/path/to/your/packaging-fork \
     --tool-repository YOUR_ACCOUNT/smart-ci \
     --tool-ref YOUR_FULL_40_CHARACTER_COMMIT_SHA \
     --output demo-output/enrollment/test.yml
   diff -u /absolute/path/to/your/packaging-fork/.github/workflows/test.yml \
     demo-output/enrollment/test.yml
   ```

   `diff` returning 1 means differences were found. Review them. The output is a
   complete candidate `.github/workflows/test.yml`, not an already-installed
   workflow. Copy it to the fork's matching path, commit it on an onboarding
   branch, and open a PR. The tool never edits the fork automatically.
3. Protect the default branch, require review of workflow/tool-pin changes, and
   require the native full test check (the existing `All pass` aggregator also
   includes the enrolled job). Protect the Smart CI source/policy repository.
   A PR can edit its own workflow YAML: pinning the tool **alone does not prevent
   that**. Where available, enforce an independently controlled required workflow;
   otherwise require trusted review of workflow changes before accepting results.
   This governance limitation must be reviewed before treating evidence as trusted.
4. Enable Actions according to your account's policy. Fork PRs may require manual
   approval; this is a platform permission gate, not automatic test selection.
   No application secrets, write token, `pull_request_target`, AWS credentials or
   model keys are needed. The lookup job alone gets `actions: read` and exposes
   `GH_TOKEN` only to the artifact-fetch step. Checkouts do not retain credentials.
5. Merge the reviewed onboarding change into the protected default branch. Its
   successful, complete Linux run should publish
   `smartci-baseline-linux-py314-<attempt>`. The first PR before that baseline will
   fall back to full. Rerun that protected push to refresh an expired baseline;
   manual dispatch is deliberately not a publication event.
6. Open a simple source-change PR. Inspect `smartci-proposal-<attempt>` and
   `smartci-result-<attempt>` artifacts. Confirm context matches the tested merge
   SHA; narrow changes should produce subset proposals if evidence is compatible.
   The execution field must remain `full`. Push a dependency change, reopen, rerun
   and force-push; verify new run/attempt and revision bindings. Change a test to
   fail and confirm the required native check fails even if analysis succeeds.
7. Set repository variable `SMARTCI_FORCE_FULL=true` to force a full proposal.
   Set `SMARTCI_DISABLE_ANALYSIS=true` to run the native path without installing
   the observer. Missing/expired baselines, removed artifacts, or optional analysis
   failures must not prevent that native execution. Reset the variables when done.
   Full rollback is restoring the original workflow/matrix cell from Git.

Use `actionlint` on the generated YAML before committing. Local validation here
uses actionlint 1.7.12; shellcheck/pyflakes are separate optional integrations.
The ignored local lint fixture uses `example/smart-ci` and a zero SHA purely for
validation. Do not install that fixture; regenerate with your published repository
and actual commit using the command above.
For manual review, GitHub documents [PR event identities](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
and [artifact metadata](https://docs.github.com/en/rest/actions/artifacts).

## Limits and costs

Local validation does not prove GitHub permission behavior, fork approval rules,
artifact service behavior, or Linux equivalence. The live verification above is
still an exit gate. Trusted baseline checks assume the protected workflow and
its maintainers are trusted; hashes detect inconsistency, not malicious authorized
producers. The artifact reader currently supports GitHub.com, not GitHub Enterprise
Server. It searches the most recent 20 matching runs and 100 artifacts per run;
missing evidence beyond those limits safely falls back to full.

Shadow mode adds discovery, installation, control-job and artifact overhead. It
does not save full-test compute yet. Artifacts expire after seven days (lookup
transfer after one); jobs have bounded timeouts and use no reusable PR caches.
Existing matrix/downstream jobs can still be expensive. Review Actions quotas and
spending controls before enabling the fork's full upstream workflow. We have not
measured a GitHub bill or claimed a monetary estimate for this unrun integration.
AWS deployment steps are not applicable: no AWS infrastructure was created.

## Verification recorded for this handoff

- `make check`: formatting, lint, strict typing and **164 tests passed**.
- `make shadow-demo`: two identical proposal digests; **62,423 native cases**
  reconciled, one reviewed Darwin skip, `complete_with_expected_skips`, baseline
  ineligible. Final artifacts: `demo-output/shadow/1795238186769078000/`.
- `make onboarding-demo`: **nine full-run scenarios passed**, including automatic
  new/deleted/renamed dependency impact and conservative configuration/dynamic
  fallback. Progress was visible before discovery and execution. Artifacts:
  `demo-output/onboarding/packaging/verification-4/`. Subsequent identifier/API
  validation hardening was covered by the final core suite and shadow demo.
- `make polyglot-demo`: all six Python/TypeScript/Java scenarios passed.
- `uv build --offline`: wheel and source distribution built. An isolated wheel
  install loaded the CLI/contracts, and its implementation digest matched source.
- Generated enrollment: actionlint **1.7.12** passed, with shellcheck/pyflakes
  integrations disabled because those tools were not installed. The generated
  patch passed `git apply --check` against the pinned pilot workflow.
- No hosted PR/push/fork workflow was run, no complete Linux baseline was observed,
  and no GitHub permissions or billing behavior was verified. The managed pilot
  was restored to its clean pinned revision. No AWS deployment or paid model calls.

## Files changed

- `src/smartci/ci/{models,github,shadow,commands,__init__}.py`: CI contracts, origin
  checks, deterministic preparation, comparison, publication and CLI subcommands.
- `src/smartci/{cli,contracts}.py`: command/schema registration;
  `src/smartci/adapters/{pytest_plugin,runners}.py`: native skip reasons, retaining
  the strict existing execution contract.
- `schemas/{ci-context,shadow-policy,shadow-comparison,baseline}.v1.json`: exported
  companion contracts.
- `scripts/{packaging_pilot,shadow_demo,ci_config,render_ci}.py`: progress, real
  shadow verification, pinned configuration and reviewable enrollment generation.
- `examples/onboarding/packaging/{shadow-jobs.yml.in,shadow-policy-local.json}`
  and `fixtures/packaging-test.yml`: workflow template, reviewed skip exception,
  and original upstream workflow fixture.
- `tests/{test_shadow,test_ci_workflow}.py`: trust, fallback, repeatability and
  native-execution regression checks.
- `Makefile`, `README.md`, `plan.md`, `docs/onboarding/{packaging,shadow-ci}.md`:
  runnable checks, scope, verification and deployment handoff.

This workspace's existing project files were already untracked; no commits or
pushes were created. Git status therefore cannot isolate this phase as a normal
tracked diff. The inventory above identifies the Phase 5 changes.
