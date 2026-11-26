# Executing native PR plans

`smartci bazel execute` derives a plan from authenticated native evidence and
executes a reviewed full or subset command. It does not accept an externally
supplied selection. The existing source-change eligibility rules remain in force:
only supported edits to existing declared C++ source inputs can authorize omissions.
Changed build definitions, unknown inputs, invalid evidence and unproven impact
retain the independent full wildcard command.

```sh
smartci bazel execute \
  --repo "$REPOSITORY_ROOT" --base "$PR_BASE" --head "$PR_HEAD" \
  --config "$TRUSTED_EXECUTION_CONFIG" \
  --bundle "$AUTHENTICATED_BUNDLE" --expected-digest "$MANIFEST_DIGEST" \
  --output "$NEW_EXTERNAL_OUTPUT"
```

Omit both map arguments to run full, or use `--force-full` for explicit rollback.
`--must-run` preserves configured mandatory targets. A wrong or dirty checkout
fails before running commands; it is not a successful full-suite check of the PR.

Export the configuration contract with `smartci schema bazel-execution`. It binds
the native profile, full/subset argument arrays and timeouts, and the exact subset
Bazel options digest. The latter differs from full only because the reviewed
adapter uses a target-pattern file. The executor writes `capture/targets.txt`;
commands write `capture/native.bep.json`. Only literal `{repo}` and `{capture}`
arguments are substituted. No shell or inherited model/GitHub credentials are used.
Configuration must come from the reviewed CI control plane, never from the PR.

Before and after execution the actual Git checkout must match the requested
commit. The native event stream must be complete and match the toolchain, options,
working directory relationship, planned target patterns and process exit code.
A subset must report exactly the selected tests and every retained build-only
configuration. Compilation failures can explain only their own unexecuted tests;
they still fail CI. Flaky, missing, contradictory or malformed evidence cannot
produce success. A full fallback can legitimately discover new targets and is not
forced to match an old inventory.

The new Abseil adapter preserves the reviewed native script, compiler, container,
workers and test flags. It changes only the wildcard to a target-pattern file for
subsets, retains bounded logs and cleans its uniquely named container. Core
execution uses bounded process groups; filesystem isolation still belongs to CI.
An environment filter alone is not a sandbox. Use disposable runners without
persisted credentials. These controls are not a guarantee of perfect dependency
knowledge or a defense against arbitrary malicious build code forging evidence.

## GitHub integration

`examples/abseil/pr-workflow.yml` demonstrates a bounded, isolated pilot. A separate
token-scoped step resolves the reviewed publisher branch and calls `bazel fetch`;
there is no saved run ID or per-PR handwritten test list. Publisher policy and the
producer's exact capture configuration are pinned in the tool checkout. Execution
then validates compatibility with the actual PR base. If retrieval or compatibility
fails, `run_pr.py` checks out that base, reconstructs the map, and restores the exact
PR head. Failed reconstruction retains full execution. PR-produced maps are not
published as trusted baselines. Failed restoration stops the job.

Planner installation failure uses the standard-library native full runner. Native
test failures are not retried or turned green by a successful planner. The pilot
is capped at 60 minutes to allow a missing-map rebuild plus head execution; routine
cache hits do not run enrollment. Artifacts expire after seven days. There are no
AWS resources or model calls.

`pr-baseline-workflow.yml` runs only the independent full native suite, with the
same source/profile and crash-report safeguards. It installs no Smart CI planning
dependencies. Use separate real PRs with identical application/test/build trees,
then compare PR-event-to-workflow-completion time, total runner time, outcomes,
native build/test counts, and action counts. Initial enrollment and cache misses
must be reported separately. A smaller plan is not a measured speed improvement.

Current verification covers subprocess execution, token filtering, full fallback,
new targets in full runs, exact subset/build-only scope, compiler failures, profile
drift, timeouts, dirty checkouts, lifecycle rebuilding and failed head restoration.
Live execution of this new path and a new end-to-end GitHub comparison are pending.
The earlier Abseil measurements belong to the previous pilot harness.
