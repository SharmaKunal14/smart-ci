# Textual production fallback and planning cost

The earlier report receipt error did **not** cause selection to fall back. The
collector recorded gaps before planning, set `graph.complete = false`, and the
selector returned `INCOMPLETE_EVIDENCE` before computing an affected subset.
The optional coverage report ran after tests. Its corrected runs are retained in
[the previous evaluation](coverage-gaps.md#completed-github-results--27-november-2026).

## What the 14 recorded gaps mean

These are the locations in the unchanged Textual source used by PRs #17/#18.
Several entries describe different aspects of the same loader; 14 gaps do not
mean 14 independent application bugs.

| Mechanism and locations | Missing evidence / actual consequence |
| --- | --- |
| `_import_app.py:63,109` changes `sys.path` | Later imports can resolve against runtime directories; the static map does not establish their identities. |
| `_import_app.py:65` calls `runpy.run_path`; `_doc.py:183` calls `exec` | Code comes from a runtime path/string. Ordinary import edges cannot enumerate its dependencies or effects. |
| `_import_app.py:111` imports a runtime module name | The app loader's complete target set is unknown. |
| `widgets/__init__.py:102,112` lazy attribute dispatch/import | Export names pass through a naming function and mutable cache before loading a module. The existing closed literal-export grammar does not verify that implementation. Type-checking-only imports are not proof of runtime dispatch. |
| `_tree_sitter.py:19` imports `tree_sitter_{language_name}` | The collector does not enumerate and validate all runtime targets/search locations for this computed name. |
| `app.py:1590` imports an environment-selected driver | The driver module and its effects are not fixed by the current collection contract. |
| `tests/test_pipe.py:16` launches a shell pipeline and Python child | The import graph lacks a verified dependency from that child execution to its app/source inputs. |
| `demo/_project_stargazer_updater.py:8` imports `_project_data` | This sibling-script import does not resolve in the collected module context. Assuming a different script search path would hide the unresolved context. |
| `tests/test_gc.py:67` imports `objgraph` on a diagnostic branch | The dependency is unresolved in the native profile. A branch unexecuted on a prior passing run can execute after a regression. |
| Native pytest plugin environment | `anyio`, `pytest-asyncio`, `pytest-cov`, `pytest-textual-snapshot`, `pytest-xdist` and `syrupy` are loaded, but no reviewed dependency contracts are configured. They are installed; the gap is their unverified effect on test dependencies, not a missing installation. |
| `snapshot_apps/auto-table.py` module spelling | The identifier-only check falsely rejected a name supported by native `importlib`. This is the bounded collector bug fixed here. |

The module-name fix retains file ownership, package initializers and import
edges. A fixture verifies actual native importlib loading of a hyphenated module,
its relative import and dependency mapping. Arbitrary code inside that file still
produces a gap. Empty/ambiguous module spellings remain unsupported. No Textual
source or test is altered to accommodate the collector.

The other mechanisms cannot be cleared by marking all observed plugins allowed,
ignoring a directory or treating previous zero coverage as proof of irrelevance.
This iteration does not claim a complete Textual dependency graph or a safe
useful subset. Clearing an unknown requires a supported dependency contract, not
model agreement or a favorable benchmark.

## Bounded efficiency changes

Previously, the harness collected base and head maps and ran native collection
twice per map, even when either incomplete map guaranteed full execution. It now
collects the head first. `required_full_from_head` validates the clean revision,
repository, implementation and exact merge base. If the head is incomplete, it
can only return a full-suite plan and skips redundant base discovery. It records
that choice without fabricating a base graph or claiming the base was complete.
If the head is complete, both maps and the original selection checks remain
required. Repeated head collection, provenance checks, all graph edges and the
independent full-suite command are preserved.

Stage durations are recorded separately from deterministic snapshot data:
input reading/probing, environment, first/repeated native collection, dependency
analysis, input revalidation and snapshot construction. They cannot alter the
selection digest. The comparison defers the optional coverage-gap report with
`--skip-coverage-report`; native pytest coverage options remain unchanged in both
arms. No model credentials or calls are present.

## Real-PR comparison protocol

The same PRs #17/#18 replay the same historical Markdown regression and artificial
uncovered-line control. Their application and test trees, pyproject and lockfile
are byte-identical to the preceding runs. Only their shared harness/tool pin is
updated. Each PR still changes only `src/textual/widgets/_markdown.py` relative
to that shared base. Native and Smart CI arms use the same revision/environment,
and the independent native full suite is authoritative for observed failures.

Report workflow-trigger-to-job completion and job duration, including setup,
discovery, planning, native tests and upload. Reconcile exact case identities,
selected outcomes and missed full-control failures. Preserve the original runs
and previous reporter failure. Fewer gaps, lower planning time, a faster full run
or fewer planned tests alone do not establish a selection speedup. No local
performance numbers are used.

## Verified GitHub results — 27 November 2026

The optimization reduces wasted planning; it does **not** deliver a safe subset
or beat the native full suite on these PRs.

| PR / GitHub run | Native trigger → result | Smart CI trigger → result | Native / Smart job time | Actual outcome |
| --- | ---: | ---: | ---: | --- |
| [#17 regression](https://github.com/SharmaKunal14/textual/actions/runs/45938297800) | 355 s | 381 s | 352 / 379 s | Same one snapshot failure; 26 s slower |
| [#18 uncovered-change control](https://github.com/SharmaKunal14/textual/actions/runs/45938296049) | 369 s | 379 s | 366 / 376 s | Both pass; 10 s slower |

Both select all **251 files**, with **3,467 case outcomes** including skips in
each arm. Exact outcomes match, with zero omitted cases and zero missed observed
full-control failures. PR #17 catches
`test_markdown_stream_switch_theme` in both arms. PR #18 has no full-control
failures, so it provides no positive regression-recall measurement.

The remaining 13 gaps are exactly the previous list minus the hyphenated-module
false rejection. Native inventory, source, dependency-edge and import digests
are identical to the preceding same-source runs. No dependency edges were
dropped to obtain this result. The audit records
`BASE_DISCOVERY_SKIPPED:HEAD_REQUIRES_FULL`; no base snapshot is invented and
`INCOMPLETE_EVIDENCE` still requires the independent full suite.

| Measured planning stage on GitHub | PR #17 | PR #18 |
| --- | ---: | ---: |
| Read/probe inputs | 0.94 s | 0.95 s |
| Probe native environment | 0.37 s | 0.37 s |
| First native pytest collection | 6.50 s | 7.06 s |
| Repeat native pytest collection | 5.55 s | 5.50 s |
| Dependency analysis and conservative shared-input edges | 2.92 s | 2.90 s |
| Revalidate unchanged inputs | 0.09 s | 0.09 s |
| Construct/validate snapshot | 1.15 s | 1.14 s |
| Complete planning, including subprocess/Git and decision overhead | **18.66 s** | **19.17 s** |

The preceding corrected runs spent 36.27 / 36.11 seconds planning. Skipping the
redundant base collection roughly halves this cost. The actual remaining
bottleneck is native pytest collection, not coverage reporting or snapshot
validation. Conservative resource-edge processing remains intact. Optional
advisory reporting now takes zero time in this path, while the unchanged native
test command still generates its original coverage evidence.

Native test-command times were 303.04 / 306.77 seconds; Smart CI's full test
commands took 308.36 / 295.09 seconds. Those differences show runner variation
and cannot be attributed to omitted tests: no tests were omitted. Whole paired
validation workflows took 381 / 380 seconds and consumed a combined **1,473
runner seconds**, excluding separate tool checks. A single pair per scenario
is not a representative average or a performance guarantee.

The [durable record](../benchmarks/textual-planning-efficiency-2026-11-27.json)
contains exact revisions, environments, job links, stage timings, artifact
hashes, graph-gap lists and previous-run references. Tool commit
`72c5c8125b3dbd6655cac40b88f12654f8e7afca` passed
[1,065 hosted tests plus formatting, lint, typing and builds](https://github.com/SharmaKunal14/smart-ci/actions/runs/45938224971).
Both PRs remain open and unmerged. No paid calls or AWS deployment occurred.

## Verify these results

1. Open the two runs above and compare their `native` and `smart` jobs. Both
   regression jobs must be red for the same snapshot failure; both control jobs
   must be green. Job duration and workflow-trigger duration differ because of
   queue/setup boundaries; both are recorded, not just pytest duration.
2. In `textual-smart-1`, inspect `selection.json`: full execution, all 251 file
   IDs, the incomplete-evidence fallback and skipped-base warning. Inspect
   `head-compatibility.json` for the 13 gaps, native inventory digest and stage
   timings. `base-compatibility.json` should be absent.
3. Check `execution.json` for `reporting_deferred: true`, zero report time and
   the preserved native exit code. Reconcile `junit.xml` with `textual-native-1`
   for exact case identities and outcomes. Native `coverage.xml` is retained;
   no optional coverage-gap receipt/report is required for this comparison.
4. Download artifacts and matching `run.json`, `jobs.json`, `subject-pr.json`
   using the pattern in the previous [verification guide](coverage-gaps.md#verify-the-published-result),
   substituting run `45938297800` or `45938296049`. Run
   `examples/textual/compare_coverage_pair.py` with the downloaded directory and
   a checkout containing the recorded Git objects. It supports the explicit
   reporting-deferred mode and still requires exact native outcome parity.

The unresolved product gate is unchanged: supported dependency analysis must
justify a useful subset, then that subset must reduce complete GitHub time.
This experiment fixes one collector error and reduces avoidable fallback cost;
it does not clear the remaining dynamic-loading/plugin evidence requirements.
