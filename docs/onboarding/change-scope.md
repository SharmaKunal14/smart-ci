# Revision-bound Python change scope

The file graph cannot distinguish changing a module-level initializer from
changing one method body. This tool supplies that missing information to the
investigator. It does not remove dependencies, certify completeness or select
tests. Its purpose is to make a later refinement depend on the actual edit rather
than assuming that every file change has the same scope.

## Contract and limits

`compare_source` accepts only a recorded changed path. The broker chooses the
input's exact base/head revisions, reads their Git blobs and validates both source
hashes. A caller cannot provide alternate revisions, replacement source or an
asserted classification. Both versions must be catalogued Python files; additions,
deletions and renames without both entries remain unsupported by this tool.

The AST comparison records one of:

| Classification | What is established |
| --- | --- |
| `identical_source` | Both bounded source byte strings are equal and parse successfully. |
| `syntax_unchanged` | Source differs, but normalized ASTs match. This is not proof of behavioral equivalence: comments, locations and formatting can be observed through source/code inspection. |
| `function_body_only` | Changes are confined to bodies of directly declared functions/methods. Module/class statements, declaration order, names, signatures, defaults, annotations, decorators and function docstrings match. |
| `module_or_definition_change` | A change falls outside those function-body boundaries, including definitions beneath control flow. |
| `unsupported` | The source cannot be parsed within the syntax/complexity limits. |

Changed-callable records contain qualified names, declaration occurrence numbers,
base/head source spans and body hashes. Nested definitions stay within the outer
function's scope. Repeated property/getter/setter names retain separate occurrence
numbers. Entry lines include decorators and are syntactic source locations, not
proof of the identity of a runtime wrapper or dynamically replaced callable.
Source literals, default values and docstrings are not returned.

Each source is limited to 256 KiB and 20,000 AST nodes. At most 256 directly
declared callables are inspected, and 32 changed-callable records are returned
with explicit truncation. Existing investigation source, response, action and
time limits also apply. AST parsing does not import or execute application code.
The verifier identity includes implementation and Python version.

**A body-only edit is not permission to omit tests.** Decorators and metaclasses
can inspect function bodies while importing a module. Reflection, source reads,
generator behavior, callbacks, aliases, dynamic calls and shared state can affect
other tests. The tool establishes syntactic scope, not a complete call graph or
runtime independence. Every result explicitly denies omission and completeness
authority. Its digest is not registered as edge evidence; the broker rejects it
if submitted as proof for a dependency proposal.

## Usage and verification

With a captured investigation input and its original Git objects:

```sh
uv run --frozen smartci investigate \
  --inputs /path/to/investigation-input.json \
  --repo /path/to/repository --module-root src \
  --provider scope-replay --output /path/to/scope-report.json
```

This offline controller inspects at most four changed Python paths and returns
the existing selection with no new edges or model calls. It is a tool-control
test, not an evaluation of model reasoning. The optional live provider can choose
the same action, but its campaign remains disabled.

The `Verify real PR change scopes` GitHub workflow audits exact source blobs from
[Textual PR #4](https://github.com/SharmaKunal14/textual/pull/4) and
[PR #11](https://github.com/SharmaKunal14/textual/pull/11). The harness pins both
revisions and source hashes and checks the complete changed-file list. It also
runs the tool through the real PR #11 investigation inputs, repeats the report
and requires unchanged graphs, unresolved gaps and independent full fallback.
The audit has a six-minute timeout, read-only permissions, no API secret and
seven-day artifact retention. No Textual tests execute in this audit; it is not
a new baseline or end-to-end CI benchmark.

Inspect `summary.json` in `textual-change-scope-1` for classifications and changed
callables, and `investigation.json` for the tool trace and preserved selection.
The normal safety workflow checks contracts, adverse inputs, source binding,
boundaries, mandatory selection, typing, lint, formatting and package builds.
No AWS deployment or additional dependency is needed.

## Next execution gate

Join an eligible edit to mechanically supported caller/fixture/runtime evidence
at matching revisions, retaining broad impact for module/definition changes and
opaque behavior. Prove that any proposed narrower scope covers the known native
profile and its shared work; a missing observation is not that proof. Then compare
native and selected execution on real GitHub PRs with ordinary, regression,
shared-change and full-fallback cases. Neither this source tool nor a smaller
diagnostic candidate list satisfies the selective execution or speedup goal.
