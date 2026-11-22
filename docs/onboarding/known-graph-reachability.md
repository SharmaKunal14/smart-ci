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
