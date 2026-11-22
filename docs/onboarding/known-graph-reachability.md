# Known graph reachability diagnostic

Resolving every unknown does not establish useful test selection. Recorded imports,
package initializers and shared fixtures can already connect a local change to
most test files. Inspect that breadth before paying for another full comparison.

The Textual plan-only command accepts `--diagnose-reachability`. It writes a
separate `known-reachability.json` using the production dependency-path traversal
over the union of base and head edges. The normal selection and fallback are
unchanged. The flag is rejected for modes that execute tests.

The report includes the actual Git comparison, both snapshot digests, aggregate
reachability, up to 16 individually mapped changed paths, and up to 20 bounded
path explanations per result. It retains unmapped changed paths explicitly.
Cycle handling and deterministic ordering are inherited from the planner;
removed edges still participate. Limiting displayed paths does not reduce the
counts. The report carries a canonical digest and cannot be consumed as a
selection plan.

Every report states `omission_authorized: false`, `execution_required: full`,
`test_execution_performed: false` and `ci_savings_demonstrated: false`.
An unreached test is not proven irrelevant. A reached test is connected under
the recorded graph model; this does not prove the dependency is exercised at
runtime. In particular, the current collector retains both conditional-import
branches. Counts of files do not establish time or compute savings.

This diagnostic is opt-in and is not added to the normal PR execution path.
It executes no additional tests or application code beyond the existing native
collection required to build snapshots. Hosted evidence will determine the next
collector work; no useful subset is presumed from the remaining gap count.

## Process dependencies are not import dependencies

The source-only Textual parser audit reached 250 of 251 files. The remaining
`tests/test_pipe.py` starts `tests/deadlock.py` through a shell/Python subprocess;
that application imports `textual.app.App`. Absence of an import edge from the
test therefore does not establish absence of a dependency. This is a concrete
counterexample to treating unreached tests as irrelevant.

The collector now records `DYNAMIC_PROCESS` for recognized process-launch APIs
from subprocess, os, asyncio, multiprocessing, concurrent.futures and pty. It also
handles imported aliases, escaped launcher references, star imports from those
modules and relevant dynamic namespace lookup. Readonly uses such as exception
classes and PIPE do not imply process execution. Literal commands still require
fallback: executable resolution, script inputs, shell behavior, working directory
and the child's environment have no supported adapter yet. No command is run to
infer those relationships.

This strengthens fallback and invalidates prior snapshots through the collector
implementation hash. It can increase the number of diagnostics; warning-count
reduction is not a safety metric. The recognized API set is not exhaustive for
arbitrary wrappers, native extensions or external processes, and no universal
completeness claim follows from it.

## Hosted evidence and decision

Both Textual PRs contain only the previously tested one-line parser regression.
The diagnostic workflows are already on their isolated base branches. Native
test files, dependencies, coverage and configuration are unchanged; collection
still finds 251 files and 3,467 cases.

| GitHub audit | Reached files | Recorded gaps | Required execution |
|---|---:|---:|---|
| [PR #9](https://github.com/SharmaKunal14/textual/pull/9), [run 45051610251](https://github.com/SharmaKunal14/textual/actions/runs/45051610251), tool `9c775322984a77a4c1f7fd3c424aa6e5cc9d01c9` | 250 / 251 | 13 | Full |
| [PR #10](https://github.com/SharmaKunal14/textual/pull/10), [run 45055835427](https://github.com/SharmaKunal14/textual/actions/runs/45055835427), tool `13b04ab3eaff4244413f1e81fa5c3e0e32eefbe7` | 250 / 251 | 14 | Full |

A representative recorded path is `_xterm_parser.py` ->
`drivers/linux_driver.py` -> `app.py` -> an application test. The import graph
operates at file granularity, so a dependency on App propagates through all of
that file's recorded imports, even when a test does not exercise those paths.
This explains the breadth; it does not prove that all 250 tests exercise the
parser at runtime.

The only unreached file is
[`tests/test_pipe.py`](https://github.com/SharmaKunal14/textual/blob/7e0ecf590c7915126e822bf55cc5ff7a4e2a6dc6/tests/test_pipe.py#L16).
It launches a Python application whose
[`App` import](https://github.com/SharmaKunal14/textual/blob/7e0ecf590c7915126e822bf55cc5ff7a4e2a6dc6/tests/deadlock.py#L6)
is outside that test's import edges. The second audit confirms an explicit
`DYNAMIC_PROCESS` at `tests/test_pipe.py:16` in both snapshots. Its source,
import, edge and case-inventory digests match the first audit. The new diagnostic
strengthens fallback without changing the recorded graph or authorizing omissions.

The implementation is [Smart CI PR #10](https://github.com/SharmaKunal14/smart-ci/pull/10).
The final code [safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45055635444)
passed 469 tests, formatting, lint, typing and package builds. Added checks cover
aliasing, namespace lookup, readonly module use and a child-script test whose
dependency is not an import edge. The actual collector must retain a full plan
for that fixture; a diagnostic report alone is insufficient.

**Decision:** do not spend another full-suite benchmark trying to obtain savings
merely by closing Textual warnings. Preserving these file-level edges reaches
almost the entire suite, and the unreached test is not proven irrelevant. Finer
runtime/context semantics remain research and adapter work, with unresolved
process, resource, plugin and side-effect boundaries. Keep Textual as a negative
compatibility/safety case. Return to native build-graph evaluation for the active
performance goal, first diagnosing Abseil's failed native environment rather than
promoting its incomplete run to a baseline. The agentic and end-to-end savings
requirements remain unmet.

No Textual test bodies were executed in these two audits, no subset was run, and
no end-to-end savings are claimed. No PR was merged, and no AWS or paid model
was used.

## Verify the results

Open the second run's **Verify source-only comparison and retained full fallback**
step. Download `textual-graph-breadth-1` and inspect `verification.json`,
`known-reachability.json`, both compatibility reports and `selection.json`.
Expect 250 reached files, one unreached file, an explicit process gap and full
execution with `INCOMPLETE_EVIDENCE`; `targets.json` is `null`.

```sh
gh run download 45055835427 --repo SharmaKunal14/textual --name textual-graph-breadth-1 --dir /private/tmp/textual-process-gap-verification
```

Artifact retention is seven days. Durable summaries and artifact hashes are in
[`textual-graph-breadth-2026-11-23.json`](../benchmarks/textual-graph-breadth-2026-11-23.json)
and [`textual-process-gap-2026-11-23.json`](../benchmarks/textual-process-gap-2026-11-23.json).
