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
