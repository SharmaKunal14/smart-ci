# Smart CI

Phases 1–4 provide a local CLI, versioned contracts, conservative selection,
read-only Git analysis, audit reports, pytest/Vitest/Maven adapters, and automatic
Python dependency discovery with revision-bound deterministic planning.
Phase 5 adds local shadow-CI contracts and a generated GitHub Actions enrollment;
OnRecord now has verified live full-suite and subset PR runs. A bounded
investigation prototype accepts independently verified dependency evidence. Its
first live model trial added no new edges or selective savings; broader evaluation,
rollout and AWS hosting remain pending.
See [plan.md](plan.md) for subsequent phases.

For progress reporting, explicit platform-skip handling, local verification and
GitHub setup, see [the Phase 5 handoff](docs/onboarding/shadow-ci.md).

The source is published at [SharmaKunal14/smart-ci](https://github.com/SharmaKunal14/smart-ci).
The [GitHub pilot walkthrough](docs/onboarding/github-pilot.md) links the packaging
fork and onboarding PR, with activation and first-PR verification steps.

## OnRecord selective execution

The new TypeScript/Vitest pilot automatically discovers file dependencies and
runs affected test files on eligible PR revisions. It reconstructs missing maps
from source; a saved baseline is optional and shadow mode is not mandatory.
See [the OnRecord handoff](docs/onboarding/onrecord.md) for exact scope, local
verification, audit artifacts, rollback and the PR-only workflow enrollment steps.
The [live subset PR](https://github.com/SharmaKunal14/slack-incidence-evidence/pull/30) passed with 64 of 103 files executed and no fallback. Both pilot PRs remain unmerged. A three-round hosted comparison reduced the old adapter's median time from 18.89 to 13.31 seconds, including planning; native full execution took 13.87 seconds. That small net advantage is environment-specific: native full execution was faster on the local Mac. See the [measurements and limits](docs/onboarding/onrecord.md#performance-investigation-and-reproducible-comparison).

## Native Bazel evidence and planning

The Abseil pilot has a verified one-job localized comparison: **655 seconds native
versus 544 seconds Smart CI from PR event to completed workflow**, retaining all
324 build-only targets while selecting 2/252 test targets. Broad changes showed no
useful benefit. See the [native comparison](docs/onboarding/native-build-graphs.md)
for exact GitHub runs, negative results, cold-cache limits and remaining work.

`smartci bazel pack` now packages validated native captures into revision/profile-bound
bundles, and `smartci bazel plan` produces deterministic plans from an authenticated
bundle digest. These installed CLI commands have no repository-specific run pins.
`smartci bazel collect` now runs reviewed native capture commands and automatically
rebuilds missing or incompatible maps, or reuses a validated compatible bundle.
Its [fresh GitHub enrollment passed](https://github.com/SharmaKunal14/abseil-cpp/actions/runs/45764627612):
252 native test targets passed, all 324 build-only targets were retained, and a
compatible map was reused without rerunning native/query commands. This does not establish arbitrary-project
compatibility or complete PR execution integration. See
[automatic collection](docs/onboarding/bazel-collection.md) and the
[bundle workflow](docs/onboarding/bazel-bundles.md)
for commands, trust boundaries, full fallback and verification.
`smartci bazel fetch` adds [trusted GitHub artifact discovery](docs/onboarding/bazel-artifacts.md)
without configured run IDs. It rejects unapproved publishers and invalid evidence;
a miss requires rebuilding or full execution. A
[separate hosted consumer passed](https://github.com/SharmaKunal14/smart-ci/actions/runs/45767540576),
including repeatable subset/full plans and tampered-map fallback. Complete automatic
PR execution remains to be integrated; these checks are not a new PR savings measurement.

## Setup and verification

Install Python 3.13 or newer and uv, then run:

```sh
uv sync --frozen
uv run smartci --help
uv run smartci validate inventory fixtures/inventory.valid.json
make check
uv build
```

If your environment restricts the default uv cache, set `UV_CACHE_DIR` to a writable
directory. Development dependencies are pinned in `uv.lock`. No AWS or model credentials are needed. Core checks run offline after setup. Polyglot
dependency installation uses public package registries; Maven may download missing
artifacts during a run.

`smartci validate KIND FILE` returns JSON and exit code 0 for valid input, 2 for
invalid/unreadable input. This reports contract validity, never test success.
Errors deliberately omit input values. Files are bounded to 5 MiB before parsing.
`smartci schema KIND` prints the JSON Schema; `make schemas` regenerates checked-in
schemas. Python validators additionally enforce path normalization, uniqueness,
and cross-field invariants not expressible by the generated schemas alone.

## Contract rules

Unknown fields, unsupported versions and type coercions are rejected. Repository
and test identifiers use bounded ASCII identifiers; callers must use stable,
repository-qualified test IDs. Paths use normalized relative POSIX notation.
The contracts validate path syntax. Execution adapters additionally resolve suite
and test paths and enforce containment within their configured roots.

Policy defaults to shadow mode and requires full execution for unknown evidence.
Future policy loading must use a protected revision: PR policy cannot weaken its
own checks. A full decision invokes an independently configured full-suite command;
its selected list is not authoritative for full discovery. Empty subsets are
invalid. Incomplete executions cannot pass. Phase 3 reconciles native results with expected execution units and binds
selective execution to the current inventory and a clean Git head.

The original provider fixture remains available. The separate `smartci investigate`
prototype adds a bounded tool loop, revision/source-bound evidence verification and
additive graph versions. Replay is the default; a [budgeted live provider](docs/onboarding/live-investigation.md)
has completed one hosted trial. Neither can remove required tests, clear gaps or override full fallback. See the [agent investigation
handoff](docs/onboarding/agent-investigation.md) for supported capabilities,
verification commands, Textual comparison scope and the approved US$5 ceiling and remaining live-call gates.

Legacy contracts require schema version `1`; the new investigation companion
contracts use their explicit `smartci.*.v1` identifiers. Breaking changes require a new schema version and
explicit migrations; readers must never guess or silently upgrade unknown versions.
No compatibility migration exists yet. Application limits are not AWS bill caps.


## Phase 2 handoff and verification

Starting point: Phase 1 validated manifests but did not select tests. Phase 2 adds
`select`, `explain`, base/current graph traversal, optional additive coverage,
full-run fallback, stable decision hashes, and JSON/Markdown reports. No new
runtime dependencies were added.

From the repository root:

```sh
uv sync --frozen
make check
make demo
uv run smartci select --inventory fixtures/selection/inventory.json --policy fixtures/selection/policy.json --base-graph fixtures/selection/base-graph.json --head-graph fixtures/selection/head-graph.json --changes fixtures/selection/narrow.json --output selection.json --audit audit.md
uv run smartci explain selection.json
uv build
```

If needed, first run `export UV_CACHE_DIR=/private/tmp/smartci-uv-cache`.
`make demo` creates ignored `demo-output/` reports. The narrow case proposes auth
and checkout, omitting other; the broad lockfile case reports `RISK_PATH` and full
execution. Both fixtures use shadow mode, so **execution remains full** even when
`mode` is `subset`. Inspect `selected`, `reasons`, `omitted`, `fallback`, and
`evidence` in the JSON. The digest covers the decision excluding its digest field;
it detects corruption, not malicious modification or authenticity.

For actual Git history, replace `--changes ...` with
`--repo /absolute/repository --base FULL_COMMIT_ID --head FULL_COMMIT_ID`.
The base graph must match the resolved merge base; the head graph must match the
actual tested commit. The `select` command consumes graphs; Phase 4's `collect`
command generates them for its supported Python profile. Git analysis rejects shallow or
ambiguous history and conservatively rejects repositories containing symlinks or
submodules. Renames include both paths and deletions consult baseline ownership.
The `select` command executes no repository source files, hooks, tests, or external
diff helpers. Phase 3 `discover` and `run` do execute trusted local code.

Graph `dependencies[A] = [B]` means A depends on B. `owners` maps exact relative
paths to components; `tests` maps current inventory IDs to components. Graphs must
include complete ownership, including test/support files. Unknown files trigger
full execution. `unsupported: true` marks reflection/dynamic behaviour the adapter
cannot model. Legacy supplied graphs declare this flag; the Phase 4 collector
sets it when its supported analysis detects unresolved or unsupported behavior.
Use protected policy and trusted graph collection; schema validity cannot prove
completeness or trust. `full_paths` uses case-sensitive path glob patterns, e.g.
`["auth/*", "**/auth/*"]`; these add to built-in risk rules and cannot remove them.

Coverage must match baseline commit, repository, and inventory environment. Valid
coverage only adds tests. Stale optional coverage is ignored with a warning;
required missing/stale coverage forces full execution. Malformed coverage files
cause full fallback even when optional. The report hashes every successfully
validated selection input. If loading fails, the fallback intentionally includes
only a fixed error code, without leaking raw paths/content.

**Selection-command consumer contract:** `select` never executes tests. Exit 0 means a report
was produced, not that tests passed. Always inspect `execution`: `full` requires
your independent full-suite command, never just the listed IDs. On any nonzero
exit, crash, missing report, or mismatch between report hashes, run the full suite
or fail the check. Never reuse a previous report after failure. Audit and decision
files are replaced individually, not as one transaction; the decision is published
last. Fresh run-specific output paths and exit-code checks are required.

Deployment: Phase 2 needs no AWS account or deployment. Local installation and the
commands above are sufficient. AWS templates and deploy instructions belong to
Phases 9–10 and do not exist yet; do not provision resources for this phase.

Verification was run on Python 3.14.7. Python 3.13 remains declared but untested.
Large-enterprise performance remains unmeasured; the demonstrations establish
behaviour on represented inputs, not perfect skip safety.

## Phase 3 handoff: real execution

**Starting point:** Phase 2 could propose selections from graph/inventory evidence,
but could not discover or execute real tests. Phase 3 adds a real polyglot example,
`discover`/`run` commands, native result adapters, and end-to-end regression checks.
No agent, model calls, workflow deployment or cloud infrastructure was added.

The example deliberately has this dependency:

```text
Python auth ← TypeScript checkout integration
Java pricing (independent)
```

Checkout invokes the Python auth process and consumes its JSON. This is a real
cross-language contract test, not a deployed cross-service system. There are
**five selectable units containing seven test invocations**: three pytest cases,
one Vitest file containing two cases, and one JUnit class containing two
parameterised invocations. IDs hash the runner-native target and include the
repository, suite and runner names. Execution reports include the native `targets`
map so the IDs remain explainable. A file or class is never labelled a single case.

### Set up and verify

Prerequisites: Python 3.13+, uv, Node **22.12+** (within Node 22) with npm, Maven
3.9+, and JDK 17+. The implementation was exercised on macOS with Python 3.14.7,
Node 22.14.0 and Maven 3.9.9 running JDK 22. Other platforms/versions have not been
verified. The process timeout implementation targets POSIX (macOS/Linux), not
Windows. The local adapters need no AWS account or credentials.

1. Install the locked Python environment and real example tools:

   ```sh
   export UV_CACHE_DIR=/private/tmp/smartci-uv-cache
   export SMARTCI_MAVEN_CACHE=/tmp/smartci-m2
   uv sync --frozen
   make polyglot-setup
   ```

   On Linux, use `/tmp/smartci-uv-cache` for the uv cache. Setup uses `npm ci
   --ignore-scripts` with the committed lockfile and runs Maven's Java tests to
   populate its cache. These downloads use public registries, not AWS or models.
   Use `uv sync --frozen --offline` if all Python packages are already cached and
   network access is unavailable. No install command can work from an empty cache
   without registry access.

2. Run core checks, including real pytest adapter checks and native-report parser
   failure cases, then build the package:

   ```sh
   make check
   uv build
   ```

   Expect formatter, lint, strict typing and tests to pass. These checks do not
   require Node/Java; the next step is mandatory to verify all three ecosystems.

3. Run the complete polyglot demonstration:

   ```sh
   make polyglot-demo
   ```

   It copies the example into a disposable Git repository, commits each change,
   reads actual Git diffs, selects units and runs them. Your source files are not
   modified. The initial full suite must pass, followed by these checks:

   | Scenario | Expected proposal/execution | Expected result |
   | --- | --- | --- |
   | Pricing multiplication defect | Java only | Java fails |
   | Auth JSON key regression | Python + TypeScript | Python passes; checkout fails |
   | Harmless auth change in shadow mode | Propose Python + TypeScript; run all | All pass |
   | Lockfile edit | Full, `RISK_PATH` | All pass |
   | Migration addition | Full, `RISK_PATH` | All pass |
   | Shared pytest setup edit | Full, `RISK_PATH` | All pass |

   The command exits 0 only if these expected outcomes hold. The two intentional
   failures are **successful verification scenarios**, not a claim those tests
   passed. Inspect `demo-output/polyglot/*.selection.json`, `*.audit.md`, and
   `*.execution.json`. Input inventory, graph, changes and policy snapshots are
   saved too. Reports include expected IDs, observed outcomes, native target names,
   return codes and adapter elapsed time (`-1` means the runner or report could not
   be obtained reliably). These timings are demonstration data,
   not a compute-savings benchmark.

4. Discover and run the unchanged example yourself:

   ```sh
   uv run smartci discover --config examples/polyglot/smartci.json --output demo-output/polyglot/inventory.json
   uv run smartci validate inventory demo-output/polyglot/inventory.json
   uv run smartci run --config examples/polyglot/smartci.json --output demo-output/polyglot/full.execution.json
   uv run smartci validate run-report demo-output/polyglot/full.execution.json
   ```

   Discovery should report `units: 5`. Run should report `status: passed` and
   `execution: full`. Open the execution JSON and confirm all five expected IDs
   have observed results across auth, checkout and pricing.

### Execution and safety contract

`smartci run` without a decision runs each configured runner's **unfiltered full
suite**. An optional `--decision PATH` consumes a Phase 2 selection report.
It re-discovers tests, validates the digest, matches the inventory digest, checks
selected/omitted IDs, and requires a clean Git head matching the decision before
allowing a subset, and checks for tracked/untracked workspace changes after the
subset. Shadow reports always run full. Malformed/missing/stale
reports fall back to full. Reports generated in the temporary demonstration are
historical evidence; using them against this working checkout causes full fallback.
Hashes detect corruption, not malicious authorship. Phase 5 adds protected-policy
and artifact-origin validation; live GitHub trust/configuration checks remain pending.

A missing, duplicate, unexpected or skipped unit, invalid native report, timeout,
collection error or failed runner without complete results cannot pass. An
incomplete subset triggers one independent full retry; an observed test failure
cannot be erased by a passing retry. Incomplete full execution exits 2. Complete
test failures exit 1; complete passing execution exits 0. Discovery errors exit 2
and require the caller to fail the check or invoke its own native full-suite
command. Never reuse old output after a nonzero exit; use fresh output paths.

Adapters use argument arrays (no shell), timeouts, fresh temporary report paths,
bounded report reads and XML entity rejection. Test/build/discovery code still
executes as your user, inherits the local environment and can access the network:
**these adapters are not a security sandbox**. Use trusted local code here and
credential-free isolated runners for future untrusted PR execution. Terminal
output is discarded to avoid retaining secrets; reproduce errors with the native
commands below. Do not put secrets in test names/parameter IDs: names appear in
reports.

### Adapter compatibility and honest limits

| Runner | Supported Phase 3 profile | Explicit limitations |
| --- | --- | --- |
| pytest | Cases/node IDs including parameter IDs; local `conftest.py` fixtures; setup/call/teardown outcomes | Uses Smart CI's plugin, disables external plugin autoload and environment addopts. Plugin-dependent suites need a reviewed adapter extension. Skips/xfails mean incomplete. Install `smartci[pytest]` for packaged use; `uv sync` includes pytest for development. |
| Vitest | Pinned single-project Vitest 4.1.12; JSON discovery/results; entire test files | Custom `vite.config.*`, `vitest.config.*` and workspace files are rejected. No workspace projects or per-case selection. Discovery loads test code. |
| Maven/JUnit | Single module; pinned Surefire 3.5.5 and JUnit 5.12.2; top-level packaged `*Test.java` classes | Source convention discovery, not a universal JVM collector. Rejects Maven profiles/modules/custom includes/excludes/test roots and JUnit nested/dynamic factories. No generated/inherited test discovery, TestNG, Failsafe or multi-module builds. The POM must route Surefire reports through `${smartci.reports}` as in the example. |

The npm lockfile pins Vite 7.3.8 alongside Vitest to keep installation compatible
with npm 10 and avoid an unnecessary Vite major-version change. The TypeScript
example also has a strict `tsc --noEmit` check, run by `make polyglot-demo`.

The example's cross-language graph is **explicit and reviewed**, not automatically
inferred. Reflective/runtime dependencies and arbitrary enterprise build layouts
remain unsupported; supply conservative full execution or extend and verify the
adapter before claiming complete evidence. Class-source scanning cannot prove the
absence of every unsupported Java feature. This is a tested compatibility profile,
not a general enterprise safety guarantee.

Coverage remains static mapping; there is no new per-test coverage collector.
Environment fingerprints cover suite configuration, Python/platform identity and
the example's dependency manifests; they do not prove hermetic tool installations
or capture every environment variable. Run on an immutable, pinned workspace.
No regression recall, unsafe-skip rate or performance savings are claimed from
these six illustrative scenarios; those measurements belong to Phase 6.

To reproduce native runner diagnostics from the project root:

```sh
(cd examples/polyglot/python && uv run --project ../../.. python -m pytest -q)
(cd examples/polyglot/ts && SMARTCI_PYTHON="$(pwd)/../../../.venv/bin/python" npm test)
(cd examples/polyglot/java && mvn -B -Dmaven.repo.local="${SMARTCI_MAVEN_CACHE:-/tmp/smartci-m2}" test)
```

JUnit XML is under `examples/polyglot/java/target/surefire-reports/`. Adapter runs
use separate fresh temporary reports and reconcile those; old native reports are
not accepted as new execution evidence.

**Deployment:** none for Phase 3. Everything above runs locally. Do not create a
Lambda, IAM role, CloudFormation stack or model endpoint. AWS templates and their
validation/deployment instructions remain later phases. Local package installation
and CI runner usage have costs separate from AWS hosting.

## Phase 4 handoff: an existing repository and automatic graphs

**Starting point:** Phase 3 required explicit dependency graphs. Phase 4 adds
`smartci collect` and `smartci plan`, using the existing **PyPA packaging 26.3**
repository as a pinned pilot. Imports, package initializers, shared fixtures and
native test ownership now generate the Python graph automatically. Ordinary PR
changes require no handwritten graph or per-PR test list.

The native pytest profile preserves upstream configuration and reviewed plugins.
This pilot plans at **test-file granularity**, with all parameterized cases in each
selected file included. Versioned snapshots record source hashes, native targets,
environment identity, collector/observer code hashes, provenance and unresolved
gaps. `plan` combines baseline/head graphs, explains dependency paths, and falls
back to full execution for missing, incompatible or unsupported evidence.

```sh
export UV_CACHE_DIR=/private/tmp/smartci-uv-cache
uv sync --frozen
make check
make onboarding-setup
make onboarding-demo
uv build
```

Setup downloads public source/dependencies into an isolated, ignored workspace;
run it once per fresh workspace. The demo takes several minutes and creates
revision-bound plans followed by full-suite ground truth. It checks native/adapter
parity, repeatability, direct/transitive changes, a newly introduced dependency,
removed/renamed dependencies, new tests and conservative fallbacks. Artifacts go
under `demo-output/onboarding/packaging/`; each repeat gets a new verification
directory. A failed run preserves its evidence and checkout for inspection.

On the verified macOS/CPython 3.14.7 profile, the independent native baseline has
**62,422 passed, one platform skip and 427 configured deselections**, spanning
17 test files. Adapter results match all 62,423 case identities/outcomes. Smart CI
continues to label the platform skip **incomplete** under its existing execution
rules. That is a disclosed compatibility limit, not a passing CI baseline.

Read the [onboarding guide](docs/onboarding/packaging.md) for exact supported scope,
scenario expectations, CLI commands, artifacts, the reversible configuration patch,
protected-baseline requirements, rollback and remaining limitations. The
[Phase 5 guide](docs/onboarding/shadow-ci.md) supplies the generated automatic PR
workflow; live enrollment remains pending. Production skipping remains gated by
Phases 6–7; this phase produces and verifies plans while executing everything.
No AWS deployment, new hosted service or paid model access is needed.

## date-fns native workspace pilot

The [date-fns guide](docs/onboarding/date-fns.md) covers the TypeScript 7 / Vitest 5
adapter, pnpm workspace reconstruction, reviewed native skips, real historical
regression replay and paired native/Smart CI benchmark. It preserves upstream
test configuration and reports total planning overhead. The bounded experiment
is complete locally and on GitHub: enrollment correctly runs everything, the
historical regression's subset catches the same six failures as the full suite,
and the real fix passes that same subset. All PRs remain unmerged. Results show
that fewer executed files do **not** imply a faster run on this already fast
native suite. This profile does not replace the repository's browser, Temporal,
other package or multi-environment checks.
