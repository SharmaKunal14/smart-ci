# Runtime dependency observation prototype

This opt-in pytest plugin records positive runtime evidence. It is not a test
selector, and its report cannot be used as a Smart CI snapshot. Every report
states `complete: false` and `omission_authorized: false`. The deterministic
selector and its full-suite fallback are unchanged.

## What is recorded

- Main-thread calls into tracked repository Python files, including calls after
  imports have been cached. Function entry locations help investigate static
  gaps; they do not prove that a particular statement or every branch executed.
- Audit events for tracked file-open attempts and Python import names. Attempts
  are not proof of successful reads or imports. External paths, file contents,
  environment values and subprocess arguments are not recorded.
- Test-call contexts grouped by test file. Collection, setup and teardown are
  shared across all tests. Other-thread audit activity has a separate shared
  context. This avoids assigning a session fixture only to its first consumer.
- Git revision and tracked blob IDs, observer hash, Python/pytest/plugin versions,
  native case count, exit status, limitations, diagnostics and a canonical digest.
  The digest detects accidental alteration; it is not a signature or proof that
  PR-controlled code told the truth.

Sorted serialization makes a fixed observation reproducible to inspect. It does
not make runtime behavior deterministic: scheduling, caching, environment and
executed branches can change observations. The assessment is deterministic for
fixed inputs; the production deterministic planner does not consume this report.

Audit hooks are bypassable and do not cover every dependency. The profiler only
covers the current thread; native extensions and child processes are incomplete.
Async tasks may outlive a test call. A clean worktree before and after execution
cannot detect transient modifications restored during a test. These limitations
remain even if all native tests pass. See Python's [audit-hook and profiler
documentation](https://docs.python.org/3.14/library/sys.html) and pytest's
[runtest lifecycle](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_runtest_protocol).

## Bounded use

Install this branch in an existing serial pytest environment, then append:

```sh
python -m pytest tests -p smartci.adapters.runtime_observer \
  --smartci-observation /absolute/path/outside/repository/observation.json
```

Preserve the repository's actual test command, dependency lock, coverage and
environment. Reports must be new files outside the checkout. The plugin rejects
dirty tracked files, non-regular Git entries, oversized metadata and xdist workers.
An existing profiler is preserved and reported as missing observation capability.
Unique observations and filename caching are bounded. Diagnostics do not convert
missing observations into permission to omit tests. Test failures retain native
pytest exit status; instrumentation/setup errors also fail visibly.

`examples/textual/benchmark.py --mode observe` runs the complete native Textual
profile with the observer, with a 900-second test-process limit. Its native mode
remains the independent control. `examples/textual/assess_observation.py` verifies
the report digest and the static-gap source revisions, lists observed consumers,
and compares call-only candidates with candidates including shared activity.
It always reports required execution as full. Neither candidate list is an
executable selection plan.

## Investigation of all 14 Textual gaps

Source: Textual commit `5e5b7ef58b8c5572c13a3ff9027d756623661495`, as preserved
by the isolated experiment branches. The two prior source-only regressions do
not modify these gap locations. The compatibility report from discovery base
`e6448b4645e8a7c2935a75abbb748ae017c145a7` supplies the locations below.

| # | Location | What the code actually does | Evidence still needed before narrowing |
|---|---|---|---|
| 1 | `_import_app.py:63` | Adds the selected script's directory to `sys.path`. | Bound script targets and resolution order, including sibling imports. |
| 2 | `_import_app.py:109` | Adds the current directory to the module search path. | Bind cwd, module targets and shadowing behavior. |
| 3 | `_node_list.py:231` | A class `__getattr__` rejects six mutation methods and otherwise raises `AttributeError`. | A narrow static rule for this closed rejection pattern; it is not a dependency loader. Runtime silence is unnecessary and insufficient. |
| 4 | `widgets/__init__.py:102` | Lazy widget lookup is guarded by a finite `__all__` list and a cache. | Validate the complete export table, transformation and target exports; retain all possible edges. |
| 5 | `_doc.py:183` | The Rich documentation formatter executes supplied source. | Establish supported test scope or constrain the formatter's inputs. Not observing its function is not proof of irrelevance. |
| 6 | `_import_app.py:65` | `runpy.run_path` executes an arbitrary app file. | Model path execution, imports, resources and inputs. Import-name analysis alone misses it. |
| 7 | `_import_app.py:111` | Imports the module name supplied by the caller. | Resolve or bound every supported caller's targets, not only the ones seen once. |
| 8 | `_tree_sitter.py:19` | Loads `tree_sitter_<language>` grammars, with an XML special case. | Bind grammar versions and the supported language set; preserve fallback for unknown inputs. |
| 9 | `app.py:1590` | `TEXTUAL_DRIVER` can select a module and class; otherwise platform defaults apply. | Bind relevant environment and platform behavior. Function entry does not prove this conditional import ran. |
| 10 | `widgets/__init__.py:112` | Converts an exported widget name to a module name and imports it. | Same closed-registry proof as #4, including the conversion helper and package initializer. |
| 11 | `demo/_project_stargazer_updater.py:8` | Standalone updater imports sibling `_project_data` as a top-level name. | Recognize the script execution root or establish exclusion from the measured test target. Do not execute its network/write behavior merely to discover it. |
| 12 | `tests/test_gc.py:67` | Imports `objgraph` only when leaked nodes remain, to produce diagnostics. | Preserve this failure-only dependency and its environment requirements. Happy-path absence cannot remove it. |
| 13 | Environment: unreviewed pytest plugins | Six loaded plugins influence async execution, coverage, workers and snapshots. | Version-bound behavioral adapters/review, including fixture and resource attribution. Observation does not make the plugin set reviewed. |
| 14 | `snapshot_apps/auto-table.py` | A hyphenated filename is passed to `snap_compare` and executed as a file. | Support tracked executable paths independently of Python module-name validity; retain its test and resource relationships. |

All source paths above are under `src/textual/` unless a `tests/` path is shown;
the last path is under `tests/snapshot_tests/`. These are 14 diagnostics, not
14 independent bugs: four belong to the app loader and two to widget dispatch.

The native lock contains anyio 4.11.0, pytest-asyncio 1.2.0, pytest-cov 5.0.0,
pytest-textual-snapshot 1.1.0, pytest-xdist 3.8.0 and syrupy 4.8.0. We inspected
the snapshot plugin's wheel after checking its existing lockfile SHA-256
`fdf7727d2bc444f947554308da1b08df7a45215fe49d0621cbbc24c33e8f7b8d`.
Its `snap_compare` fixture resolves a relative app path against the test file's
directory and invokes Textual's `import_app`, then captures a screenshot and
compares it with Syrupy. Consequently the loader and hyphenated app are real
test relationships, not harmless filenames to exclude.

The other five wheels were also checked against their existing lockfile hashes
and their plugin entry points inspected. anyio wraps async fixtures and calls;
pytest-asyncio substitutes scoped runners and fixture synchronizers; pytest-cov
registers during initial conftest loading; xdist can dispatch into worker
processes; Syrupy tracks collection, outcomes, snapshots and session completion.
This bounded source inspection is not a full review of their transitive behavior
and does not make them eligible for a collector allowlist. It did reveal that a
session-finish plugin may change the final exit status, so the observer now reads
`session.exitstatus` after earlier finish hooks, with a focused regression check.
The benchmark's independent process exit code remains authoritative.

## Hosted verification

Implementation is isolated in [Smart CI PR #6](https://github.com/SharmaKunal14/smart-ci/pull/6).
[Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6) replays the same
historical parser regex regression used by the earlier comparisons. Its two jobs
run the full suite at the same PR head. Only the observe job loads this plugin;
native tests, coverage, dependency lock and worker settings are unchanged.
The observer is pinned to `e878d8b1d9c3e50a19a51476c6115e6239e91c15`.
Both jobs are expected to retain the real parser failure. A red native regression
is not to be suppressed to obtain a green experiment.

The [GitHub run](https://github.com/SharmaKunal14/textual/actions/runs/45033123042)
completed both full commands with 3,467 cases. Every case identity, outcome and
skip identity matched. Each job retained exactly the same failing parser case,
`tests.test_xterm_parser::test_extended_keys[\\x1b[58;2;126:47u-~/]`.
The red checks represent the deliberately replayed defect, not extra failures
introduced by the observer in this run.

| GitHub measurement | Native full suite | Full suite with observer |
|---|---:|---:|
| Workflow creation to job result, including queue/setup/upload | 387 s (6m 27s) | 755 s (12m 35s) |
| Entire job | 385 s | 752 s |
| Test process | 334.94 s | 693.17 s |

Instrumentation added 368 seconds to end-to-end feedback in this single pair.
There were **no savings and no actual test omissions**. This is one observation,
not a repeated estimate; setup and runner variability are included. The observer
is unsuitable for the PR hot path on these measurements. If improved later, its
natural role would be collecting evidence during a baseline/full-suite run.

The report contains 737 executed tracked files and 1,349 tracked file-open
attempt paths. Most significantly, **122 executed files lie outside the current
`src/` and `tests/` collector roots**: 114 documentation examples and eight files
under `examples/`. The snapshot suite actually loads them. Opens also include
109 `.tcss`, 448 `.svg` and 15 `.scm` paths. These are observed attempts, not a
complete resource graph. Silencing the 14 diagnostics would not fix these
missing scope/resource relationships.

| Candidate change | Files with observed test-call activity | With the prototype's shared activity included | Authorized selection |
|---|---:|---:|---|
| `_xterm_parser.py` | 1 / 251 | 251 / 251 | Full |
| `widgets/_markdown.py` | 5 / 251 | 251 / 251 | Full |

The parser candidate includes the file containing the failing case; **we did
not execute that candidate as a subset**. Parser constructor, `parse` and
`debug_log` entries also occur in the shared context, consistent with its
function-scoped `parser` fixture. Markdown's shared entries include module and
class initialization. The deliberately coarse shared treatment loses useful
ownership information. It is not evidence that every test truly depends on
these modules, nor proof that a more precise hybrid collector is impossible.

Runtime evidence connects the app loader and hyphenated app to the snapshot
test file. The widget loader appears in eight test-call files plus shared
activity, grammar loading in four, and `get_driver_class` in 163 plus shared
activity. The GC helper is entered in its own test. The readonly hook, Rich
formatter and updater have no recorded entries. **Function entry does not show
that the problematic statement ran; zero entries do not discharge a gap.**
The report additionally flags child processes and untracked/external opens as
unattributed. No observation limit was reached. All 14 gaps remain unresolved
for production selection; `complete` and `omission_authorized` remain false.

The tested observer commit is recorded above. The later session-finish metadata
correction does not change dependency attribution; the observed and native
process exit codes were already both 1. Its additional behavior is covered by
the Smart CI safety workflow rather than another expensive Textual rerun.

## What to verify and what comes next

1. Open [Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6), then its
   Checks or the run linked above. Inspect the native and observe test steps.
   Both should show the same one parser failure; do not expect green checks for
   this deliberately regressed source.
2. Download `textual-native-1` and `textual-observe-1` from the run's artifacts.
   Compare their `junit.xml` and `execution.json`. Inspect `observation.json` for
   `contexts`, diagnostics, hashes, and the two explicit false safety fields.
   GitHub artifacts have seven-day retention; the checked summary persists in
   `docs/benchmarks/textual-runtime-2026-11-23.json`.
3. To reproduce the analysis of those artifacts, use the assessment script with
   `--repo` pointing to the fork checkout containing both commits,
   `--observation` pointing to the downloaded report, and `--compatibility`
   pointing to the previous base compatibility report. Pass each source path
   with `--path` and a new `--output`. The script validates source equivalence
   and report integrity before emitting candidates, never a subset plan.

The next useful increment is fixture ownership and lifecycle attribution,
including function/session scopes and asynchronous work, plus a version-bound
snapshot adapter for tracked path-loaded apps and their resources. Expand the
graph to include the discovered documentation/example files. Add narrow static
rules for the closed readonly hook and widget registry, with adversarial tests.
Keep full fallback for inputs, drivers, plugins or execution paths those
contracts cannot account for. Only then test an eligible subset against the
independent native full suite on real PRs. One recorded run alone cannot replace
those contracts or establish safety for future changes.

No AWS service or paid model is used; all PRs remain unmerged.

The follow-up [scoped observation experiment](runtime-scoped-observation.md)
separates collection and fixture setup and tests a monitoring backend. Its hosted
pair preserves all outcomes but still requires all 251 files; background parser
execution and shared file opens remain unresolved. It does not supersede this
run's negative result with a claim of selective-CI savings.
