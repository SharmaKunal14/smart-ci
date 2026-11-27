# Native GitHub Action (alpha)

The Action runs the reusable Smart CI CLI on the customer's GitHub runner. It
installs a pinned, checksum-verified release and its hash-pinned dependencies,
derives the PR base/head from GitHub, retrieves approved dependency evidence or
rebuilds it, then invokes the supported native tests. No CLI service, AWS account,
model credential or paid model call is involved.

This release starts with the existing reviewed Bazel contract. The bundled
`abseil-gcc-cpp17-v1` adapter is specifically for Abseil's pinned GCC/C++17
fastbuild profile, including its native image, flags and build-event validation.
It is **not** a general adapter for every Bazel repository. A different native
profile needs reviewed capture/execution commands and evidence validation before
it may omit tests. Python/TypeScript pilots remain separate existing adapters.

## Customer workflow

Keep the repository's existing native environment setup. Replace its test step
with the Action; the Action installs the CLI itself. Pin `uses` to a reviewed
40-character Action commit. The release pin inside that commit also names the
exact wheel version and SHA-256. Do not use the moving development branch.

```yaml
on:
  pull_request:
permissions:
  contents: read
  actions: read
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      # Preserve the existing native toolchain/environment preparation here.
      - uses: SharmaKunal14/smart-ci@REVIEWED_ACTION_COMMIT
```

For the bundled profile, `.smartci/native.json` starts as:

```json
{"schema_version":"1","profile":"abseil-gcc-cpp17-v1"}
```

The preset ships the reviewed adapter, so customers do not copy its Python
scripts. Without an approved publisher, the Action rebuilds the map from the exact
base before planning. That includes a full native enrollment and may cost more
than a full PR run. Routine savings require reusable evidence: add `publisher`
and `publisher_capture` contracts from the reviewed enrollment configuration.
They bind the repository, producer branch, workflow digest, artifact age, native
profile and capture command identity. See [artifact onboarding](bazel-artifacts.md).
Do not paste another project's policy or edit hashes merely to bypass rejection.

For an already reviewed custom adapter, the full policy form accepts `capture`,
`execution`, `fallback`, optional `publisher`/`publisher_capture`, and `files`.
It uses the [native Action policy schema](../../schemas/native-action-policy.v1.json).
Listed adapter files are loaded from the exact PR base into an external control
directory. `{control}` refers there, `{action}` to the pinned Action, `{repo}` to
the source checkout and `{capture}` to the invocation's evidence directory.
Commands are bounded argument arrays, not shell strings. The independent full
fallback must work without Smart CI or its Python dependencies installed.

## Trust and failure behavior

- Only ordinary `pull_request` events on disposable GitHub-hosted Linux x64
  runners are supported. `pull_request_target` is rejected. Do not expose private
  credentials or persist Git credentials before executing PR code.
- The source checkout must be the exact clean PR head, with the base commit
  available. Configuration and custom adapter files come from the base, so a PR
  cannot approve its own selection policy. Onboarding must first be reviewed on
  the base branch; a config introduced only in the PR is rejected.
- The Action's read-only token exists only in the evidence-retrieval step. The
  native child environment is allowlisted. This is not filesystem isolation;
  native build/test code executes on the runner with normal job privileges.
- Missing, stale or rejected evidence causes base reconstruction or full
  execution. Failure to restore the head stops the job. PR-produced maps are not
  published as trusted baselines.
- Installer or control-plane preparation failure runs the reviewed independent
  full command. Native failures are propagated, never retried to conceal a red
  result. Invalid PR context or missing/untrusted policy fails visibly before
  executing code, since no safe full command is known.
- Selection retains required build-only targets and mandatory tests. Unsupported
  file changes, build/configuration drift or evidence-integrity failures require
  full execution. A full run uses the native wildcard, not an old inventory.
- The declared C++ input model is a reviewed assumption, not proof that arbitrary
  Bazel code is hermetic. Undeclared file/network/runtime dependencies can invalidate
  that model. Do not enable omissions for a profile with such unresolved behavior.

`force-full: 'true'` bypasses map reconstruction/selection and invokes the
independent full native execution path. Inputs `path` and `config` change the
checkout/config locations. The summary outputs `mode`, `status`, and
`selected-tests` (Bazel targets, not individual cases). Native reports and plans
are retained for seven days. Missing/invalid reports are never labelled passed.

## Verification and rollout

1. Review the selected native profile and its existing full command. Set up
   read-only GitHub permissions, a clean head checkout, and protected base-owned
   configuration. Preserve native cache settings; never disable caching to claim
   a Smart CI speedup.
2. Run a normal source-only PR with an independent unchanged full control on the
   same source/environment. In the Action log, verify the pinned release was
   installed, then inspect map status and full/subset execution. Download
   `smartci-native-<job>-<attempt>` from the workflow artifacts.
3. Inspect `native-pr/lifecycle.json`, `execution/plan.json`, and
   `execution/execution.json`. Confirm exact base/head, map admission,
   fallback reasons, selected targets, retained build-only scope and complete
   reconciled native events. Compare failures with the independent control.
4. Check a real regression and a build/configuration change. The regression
   must remain red; unsupported changes must run the independent full suite,
   including any new tests. Missing maps must rebuild or run full, not skip.
5. Measure event-to-result and job duration including checkout, installation,
   map fetch, planning, native execution, validation and artifact upload.
   Include enrollment separately, record runner CPU differences, and retain
   negative results. Fewer selected targets alone is not success.

For maintainers: `uv sync --frozen`, `make check`, and `uv build` verify code,
contracts, typing, formatting and regression tests. Hosted safety checks also
install the native TypeScript toolchain; local skips are not a hosted pass.
Release artifacts are taken from the successful hosted safety run for the exact
release commit, then pinned by digest. No source merge is required to test a
prerelease Action SHA. Production adoption still requires the customer's review.

## Evidence status

The new Action's hosted installation and paired PR verification are pending.
Prior CLI-based cold Abseil comparisons selected 2/252 test targets and retained
324 build-only targets, with 626/413 and 724/497 seconds native/Smart CI. Prior
warm-cache comparisons were slower with Smart CI: 198/209 and 289/307 seconds.
These are limited historical cases with differing runner CPUs, not a universal
savings claim. See [the prior execution evidence](bazel-execution.md) and
[warm-cache results](native-cache-evaluation.md).
