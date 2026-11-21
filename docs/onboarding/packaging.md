# Phase 4: onboarding the existing PyPA packaging repository

This is the Phase 4 handoff and records that phase's verification. See the
[Phase 5 handoff](shadow-ci.md) for the subsequent progress, skip-policy and CI
implementation; live GitHub enrollment is still pending.

## Starting point and delivered scope

Phase 3 executed Python, TypeScript and Java tests using explicitly supplied graphs.
Phase 4 adds an automatic Python collector and a snapshot-aware `smartci plan`
command. The existing selection engine and graph schema remain compatible.
No application runtime dependency was added to Smart CI.

The chosen pilot is the real [PyPA packaging library](https://github.com/pypa/packaging),
pinned to release **26.3**, commit
`929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5`. A disposable local clone is used;
nothing is pushed to PyPA. This is evidence for one Python profile, not enterprise
or cross-language validation.

| Compatibility item | Enrolled scope / limitation |
| --- | --- |
| Working directory and native command | Repository root; `python -m pytest`, using the repository's configuration. |
| Runtime verified | CPython 3.14.7, macOS ARM64. Other operating systems, Python versions, free-threaded builds and PyPy remain unverified. |
| Test configuration | Upstream `pyproject.toml`, including strict configuration/markers, warnings-as-errors and `-m 'not property'`. Nothing clears `addopts` or disables plugin autoload in this profile. |
| Discovery and execution | 17 file-level units; every native case in a selected file is included. Parameterized case IDs are retained for reconciliation. |
| Dependencies and plugins | Upstream test-group requirements, pinned for this harness in `examples/onboarding/packaging/requirements.txt`; Hypothesis remains loaded. Upstream dependency files are unchanged. |
| Shared fixtures | `tests/conftest.py` remains active. Its import dependencies reach every test using that conftest scope. |
| Native baseline | 62,422 passed, one glibc-only test skipped on macOS, 427 property cases deselected by the upstream configuration. Adapter and independent JUnit results matched every executed case identity and outcome. |
| Other existing jobs | The upstream [Nox wrapper](https://github.com/pypa/packaging/blob/929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5/noxfile.py) also runs coverage; the [workflow](https://github.com/pypa/packaging/blob/929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5/.github/workflows/test.yml) has a much larger platform/interpreter matrix and separate property/downstream/pickle jobs. Those wrappers, gates and jobs are preserved and are **not enrolled or claimed verified** by this pilot. |
| Services | The enrolled pytest profile needs no database, cloud account or deployed service. Downloads are needed during setup; verification uses local installed tools. |

The existing execution contract treats any skipped case as incomplete. Consequently
the adapter's full result is `incomplete` on this macOS profile, even though native
pytest exits 0. The matching platform skip is explained, not converted to a pass.
These local snapshots are not eligible for automatic trusted CI baseline promotion.
Phase 5 must explicitly address native skip semantics or validate a profile without
the skip before enabling promotion. Missing results and unexpected skips must never
be accepted as a successful run.

## How the automatic graph is built

1. Require a clean committed checkout. Read its tracked source/test files and record
   SHA-256 hashes, the actual Git commit and the collector implementation digest.
   Symlinks, submodules, dirty checkouts and excessive input fail collection visibly.
2. Parse ordinary Python imports with the AST. Resolve local packages, relative
   imports, reexports and package initializers. Keep conditional local imports on
   both branches. Python module names resolve to stable file nodes; no test-name
   similarity or handwritten file-by-file graph is used.
3. Check top-level source origins using the target interpreter's `PathFinder` and
   metadata. It does not explicitly import application modules to resolve them.
   Native pytest collection **does** execute repository code. Interpreter startup
   can also run environment hooks: this is trusted local execution, not a sandbox.
4. Collect pytest twice and compare native case identities. Map each discovered
   execution unit to its containing test file. Include containing `conftest.py`
   files and their imports. Conservatively treat tracked package/test data as shared
   input to all enrolled tests; arbitrary resource reads are not guessed.
5. Record installed distribution versions, Python/ABI/platform, pytest configuration,
   reviewed plugins, relevant ambient-setting hashes and observer/collector code
   hashes. Source-dependent lookup answers stay in revision provenance rather than
   being mistaken for changes to the installed environment. Native runs use a fresh
   bytecode-cache location to avoid stale `.pyc` files across revisions.
6. Generate baseline and head snapshots. Planning checks compatibility, resolves the
   Git comparison, and traverses reverse dependencies over **both** graphs. Removed
   imports and renamed files cannot erase baseline impact. New tests enter the
   inventory automatically. Reports include a stable dependency path where available.

The small onboarding configuration declares import/test roots, execution granularity
and reviewed exceptional behavior. It does not list test IDs or import edges.
For this pilot, native fixtures temporarily replace two **external** modules,
`_manylinux` and `ctypes`, using pytest's `monkeypatch.setitem`. Those reviewed names
are explicit in `external_module_overrides`; the collector records each accepted
literal override. Unknown names, nonliteral overrides, direct registry access, or
an override that now resolves to a local module cause an analysis gap. The policy
also forces full execution when these platform-mocking test files change.

Optional absent platform modules and external imports under recognized type/version
guards are recorded separately. Existing local dependencies are never dropped by
these guards. An external module available outside recognized metadata remains
unresolved. The environment's standard virtualenv finder is recognized and hashed;
unknown import hooks require full execution.

## Reproduce the phase

Run these commands from the Smart CI repository, with Python 3.14, uv and Git
available. Use a writable uv cache; on Linux use `/tmp/smartci-uv-cache` instead.

```sh
export UV_CACHE_DIR=/private/tmp/smartci-uv-cache
uv sync --frozen
make check
make onboarding-setup
make onboarding-demo
uv build
```

- `make check` runs formatting, lint, strict typing and the offline core tests,
  including real temporary Git repositories and pytest executions. It does not
  download the pilot or run its 62,423 cases.
- `make onboarding-setup` downloads the pinned public repository, creates a separate
  environment, installs its pinned tools and editable application, builds a Smart CI
  wheel, and installs only that wheel's observer into the pilot environment. It
  refuses to overwrite an existing setup. All output lives in ignored
  `demo-output/onboarding/packaging/`.
- `make onboarding-demo` independently runs native pytest, compares every native
  case with the adapter's full result, then verifies the scenarios below. Every
  proposal is saved **before** obtaining full-run results. Every scenario executes
  the full suite. Allow several minutes; this is an acceptance harness, not a
  performance optimization for normal development.
- `uv build` produces the wheel and source archive. There is no AWS deployment step.

The target environment installs the wheel with `--no-deps` specifically for the
pytest observer, which imports only pytest and the standard library. Run the Smart
CI CLI from its own complete `uv` environment, not from the target environment's
CLI entry point. This avoids changing the application's dependency set for the
collector; a separately distributed observer is future packaging work.

Each successful verification restores the managed clone to the pinned revision.
Repeated verification creates a new `verification-N/` directory; it does not replace
earlier evidence. `latest-verification.json` points only to the last completed run.
If setup is interrupted, or the managed clone is dirty, the harness preserves it
for inspection rather than resetting it. Create a separate disposable workspace:

```sh
uv run --frozen python scripts/packaging_pilot.py setup --workspace /private/tmp/smartci-packaging-second
uv run --frozen python scripts/packaging_pilot.py verify --workspace /private/tmp/smartci-packaging-second
```

| Scenario | Expected proposed files / reason | What verifies it |
| --- | --- | --- |
| Unchanged baseline | All 17 files executed | Native/adapter case identities and outcomes match; repeated snapshots match exactly. |
| License defect | License and metadata tests | Removing the MIT license entry breaks metadata validation. The candidate includes that downstream failure, even though the license tests themselves pass. |
| Added dependency | `tests/test_direct_url.py` | An ordinary import and call to the license parser enter the graph automatically. No graph or test-list edits. |
| Indirect defect | License, metadata and direct-URL tests | Changing only license data now affects an additional file through the newly discovered import. Full execution confirms failures in metadata and direct-URL tests. |
| Removed dependency | License, metadata and direct-URL tests | Old and new graphs participate when the import is removed and upstream data changes. |
| Renamed module | License and metadata tests | Both rename paths and updated imports are discovered from Git/source. |
| New test | Newly discovered test file | Native discovery grows without editing a Smart CI test manifest. |
| Configuration change | Full, `ENVIRONMENT_MISMATCH` | The configured test environment changed; narrow evidence is not reused. |
| Dynamic import | Full, `INCOMPLETE_EVIDENCE` | The unresolved dynamic loader appears in provenance and audit warnings. |
| Missing baseline | Full, `INVALID_OR_UNAVAILABLE_SNAPSHOT` | The CLI emits an explicit full-execution requirement. |

The two seeded defects demonstrate detection in these particular cases. They do
not establish production regression recall or an unsafe-skip rate. The harness
records collection and full-run wall times in `verification.json`; no compute
savings are claimed while running in shadow mode.

The implementation verification completed **all nine scenarios**, native identity/
outcome parity, snapshot repeatability, missing-evidence fallback and patch validation.
The final core suite passed **100 tests**, formatting, lint and strict typing; the
existing six-scenario polyglot demo also passed. Wheel and source builds succeeded,
and the wheel's CLI was checked in a separate environment. In one local run,
collection took **13.22–14.04 seconds** per snapshot and full adapter execution
took **28.83–30.51 seconds**. Collection currently runs twice for a stability check.
These are observed local timings, not enterprise benchmarks; shadow collection
adds work, and net selective savings remain to be measured in later phases.

## Inspect and replay the evidence

On the first successful default run, inspect:

```sh
uv run smartci explain demo-output/onboarding/packaging/verification/license-defect/selection.json
uv run smartci validate snapshot demo-output/onboarding/packaging/verification/baseline/snapshot.json
```

For later runs use the directory printed by the harness. Each scenario includes
`inventory.json`, `base-graph.json` (when comparing), `head-graph.json`,
`provenance.json`, `snapshot.json`, `selection.json`, `audit.md` and full results.
`native-results.json` contains case outcomes; `full-result.json` contains file-level
execution reconciliation. Test names may contain parameter data: these are local
ignored artifacts, not automatically published logs.

`snapshot.json` is the self-contained input to `plan`. Its digest and cross-field
checks bind the inventory, graph and provenance together. The other files are
inspection copies; editing them does not change the bundled evidence. Hashes detect
inconsistency, **not authenticity**. A party able to rewrite every artifact can
recompute a digest; protected CI origins remain Phase 5 work.

For a newly onboarded clean checkout, the general interface is:

```sh
uv run smartci collect --repo /absolute/pilot-checkout --python /absolute/pilot-env/bin/python --config /absolute/protected/collector.json --output /absolute/artifacts/base
# In a separate clean checkout or after checking out the actual tested head:
uv run smartci collect --repo /absolute/pilot-checkout --python /absolute/pilot-env/bin/python --config /absolute/protected/collector.json --output /absolute/artifacts/head
uv run smartci plan --repo /absolute/pilot-checkout --base-snapshot /absolute/artifacts/base/snapshot.json --head-snapshot /absolute/artifacts/head/snapshot.json --policy /absolute/protected/policy.json --output /absolute/artifacts/selection.json --audit /absolute/artifacts/audit.md
```

The base checkout must be the actual merge base. Reinstall the application correctly
for each checkout/environment; the collector checks that native source origins
match. Use fresh output directories outside the target checkout. `collect` exits 0
when evidence was produced, including evidence explicitly marked `full_required`.
With `--run-full` it also writes native/full-run reports and exits 0/1/2 for
passed/failed/incomplete execution. `plan` exit 0 means a proposal was written,
never that tests passed. A nonzero exit, missing output or incompatible snapshot
must keep the existing native full command authoritative. No command here enables
automatic PR triggers or authorizes production test skipping.

## Protected baseline bundle and future CI integration

The proposed protected-branch bundle consists of the canonical snapshot, its
inventory/graph/provenance inspection copies, native/full results, the pinned
collector package digest and protected policy digest. A separate publication
envelope must bind repository, tested commit, environment/matrix, workflow/run ID,
publisher and completion time. Incidental times stay outside deterministic
selection inputs. Phase 5 must validate artifact origin and use a documented expiry
(initial proposal: seven days), plus immediate invalidation on collector, policy,
configuration or environment changes. Refresh after an eligible complete protected
full run; absent, expired or incompatible evidence keeps execution full. Local JSON
has no trusted publication or expiry enforcement yet, and selected-only results
cannot establish a full baseline.

The reversible [configuration patch](packaging.patch) adds only `.smartci/collector.json`
and `.smartci/policy.json`. Validate it without applying it:

```sh
git -C demo-output/onboarding/packaging/repository apply --check ../../../../docs/onboarding/packaging.patch
```

Alternatively use an absolute path to the patch. Applying the proposal in a
maintained fork would require committing/reviewing those files before collection;
it does not change the native workflow. The harness checks this patch automatically.
Remove it with `git apply -R /absolute/path/to/packaging.patch` if it was applied and
not subsequently changed. No upstream PR is opened.

To verify operation without Smart CI, use the original command in the managed clone:

```sh
cd demo-output/onboarding/packaging/repository
../environment/bin/python -m pytest -q
```

The observer is loaded explicitly, not via an auto-loading entry point, so this
native command does not load it. Original source, dependency files and CI jobs remain
available. Once local evidence is no longer needed, the disposable workspace can
be removed; no cloud teardown or credentials are involved.

## Known limits and the next phase

- This collector supports regular Python packages and pytest's ordinary import
  behavior. Namespace-package ambiguity, unresolved imports, detected dynamic
  loading, custom import paths, unreviewed plugins and local `pytest_plugins`
  declarations require broader execution or explicit compatibility work.
- The analysis is conservative under its supported model. Detecting several
  dynamic patterns is not proof that arbitrary Python reflection, native extensions,
  hidden environment dependencies or external services have been fully modeled.
- External distributions are treated as opaque inputs in an assumed pinned,
  immutable environment. Version fingerprints do not prove that installed files
  were never modified in place. Two matching collection runs establish observed
  repeatability, not a proof that every possible test generator is deterministic.
- This pilot uses pytest's default package/import behavior and upstream default
  marker expression. Custom wrappers, import modes and cache-dependent filters
  such as `--last-failed` need separate enrollment checks; this collector is not a
  universal validator of arbitrary pytest configuration.
- The shared marker-cache fixture can make central-module changes reach all 17
  files. That is a consequence of the recorded dependencies, not evidence of savings.
- Git/runner handling is POSIX-oriented. Large-enterprise performance, Windows,
  other Python versions, coverage-based mapping and automatic TS/Java discovery
  have not been validated here.
- Phase 5 still needs automatic PR triggers, protected policy/baseline loading,
  fork isolation, native full-job preservation and CI artifact publication. Phases
  6–7 measure detection/savings and gate selective execution. AWS and agent work stay
  deferred. This phase creates no AWS resources or paid model usage.

## Changed files

- `src/smartci/discovery/`: `models.py`, `environment_probe.py`, `python_graph.py`,
  `collector.py`, `planning.py`, `commands.py` and `__init__.py` add the collector,
  companion contracts, provenance and snapshot planning.
- `src/smartci/cli.py`, `src/smartci/adapters/runners.py` and
  `src/smartci/adapters/pytest_plugin.py` expose the commands, preserve the native
  pytest profile and reconcile every case within file-level units.
- `tests/test_discovery.py` and `tests/test_adapters.py` cover discovery, native
  compatibility, deterministic plans, fallbacks and output boundaries.
- `schemas/python-collector.v1.json` and `schemas/snapshot.v1.json` publish the new
  contracts; the original graph contract is unchanged.
- `examples/onboarding/packaging/` contains configuration, policy and dependency
  pins. `scripts/packaging_pilot.py` and `Makefile` provide repeatable setup/acceptance.
- `README.md`, `plan.md`, this guide and `docs/onboarding/packaging.patch` document
  the handoff, supported scope, reproducible checks and reversible proposal.
