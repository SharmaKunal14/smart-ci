# Closed rejecting attribute hooks

The Python collector now recognizes an attribute hook that can only reject a
name. This addresses the readonly `__getattr__` diagnostic in Textual's
`src/textual/_node_list.py`; it does not establish Textual-wide compatibility.

Supported bodies contain an optional docstring, zero or more membership tests
against literal string sets/lists/tuples, and an unconditional final raise. Every
branch raises `AttributeError` or a module-local, otherwise empty subclass of
`AttributeError`. Arguments are a literal string or the requested name. No return,
loader, interpolation, additional call, mutation or exception chaining is accepted.

Exception binding checks conservatively include imports, function parameters,
assignments, deletion, exception handlers, pattern captures and type parameters.
Custom exception constructors, decorators and metaclasses remain unsupported.
A local exception must have exactly one definition, and its only uses must be
the recognized raise sites; aliasing or mutation retains the diagnostic.
Asynchronous attribute hooks also remain unsupported.

The collector still visits the complete source. Other imports and diagnostics
remain, including the lazy widget registry, arbitrary app loading, plugins,
path-loaded snapshot apps and runtime resources. No application code is executed
to recognize the grammar, no dependency is inferred from a successful test, and
no runtime observation is promoted to omission authority. The implementation hash
changes with this rule, invalidating reuse of snapshots from the prior collector.

These checks describe one supported source pattern within the existing static
collector's assumptions. They are not a proof against arbitrary monkey-patching,
unmodeled external behavior or all Python metaprogramming. The generic visitor
and environment checks continue to handle their supported uncertainty signals.

The Textual widget registry is **not** accepted by this change. A finite export
list alone does not prove the computed import targets: its conversion helper,
cache and dispatcher still need supported, revision-bound analysis. Import and
attribute-hook diagnostics remain for it.

## Verification

`tests/test_attribute_hooks.py` covers the supported grammar and mutations that
must retain fallback. Existing Python resolution and collection tests verify
that import edges, graph construction and native inventory behavior still work.

The [Smart CI safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45047350062)
passed 431 tests, formatting, lint, typing and wheel/source builds at adapter
commit `9a2ec11d7911f237b575f814d84a00444e9f3825`.
Implementation is [Smart CI draft PR #9](https://github.com/SharmaKunal14/smart-ci/pull/9).

[Textual draft PR #8](https://github.com/SharmaKunal14/textual/pull/8) compares the
previous collector `0260615ca6d6764a16be7d525d3663ff42a5b0b7` with that adapter.
The [completed discovery run](https://github.com/SharmaKunal14/textual/actions/runs/45049809987)
passed at Textual head `114b69e248a0c7e8aa8b38a3bd5d154dc988a3dc`.
Both collectors use the same native locked environment and identical collection
observer; observer installation uses `--no-deps`.

| Hosted check | Previous collector | Revised collector |
|---|---:|---:|
| Base diagnostics | 14 | 13 |
| Head diagnostics | 14 | 13 |
| Collected test files | 251 | 251 |
| Collected case identities | 3,467 | 3,467 |
| Required execution | Full | Full |

The only removed diagnostic is `DYNAMIC_ATTRIBUTE_HOOK` at
`src/textual/_node_list.py:231`. Case identity digests, source hashes, environment,
plugins, imports and dependency edges match for each revision across collectors.
Planning is repeated from the same snapshots and must produce identical output.
Both final plans retain `INCOMPLETE_EVIDENCE`, with no selected-target command.

The initial [audit attempt](https://github.com/SharmaKunal14/textual/actions/runs/45047371112)
failed before collection because the workflow omitted the native collection
observer. The corrected workflow checks that the two observer files are identical
and installs it without changing native dependencies. No failing application
tests were removed or changed.

This is a discovery diagnostic, not a test-time benchmark. Native collection
loads application and plugin code, but no test bodies or subset were executed.
There is no new performance result. The remaining 13 diagnostics still prevent
omissions. Closing diagnostics also does not establish that the resulting graph
will yield a useful subset: shared imports and package initializers can require
many tests even when every edge is known.

## Inspect the hosted evidence

Open the run above and inspect **Verify exact diagnostic change and preserved
full fallback**. Download `textual-discovery-audit-1`; it contains
`comparison.json` and each collector's base/head compatibility, selection and
targets reports. The artifact retention is seven days. For example:

```sh
gh run download 45049809987 --repo SharmaKunal14/textual --name textual-discovery-audit-1 --dir /private/tmp/textual-readonly-verification
```

Expect 14-to-13 diagnostics at both revisions, `execution: full`,
`test_execution_performed: false`, `ci_savings_demonstrated: false`, and `null`
targets. The compatibility reports include the identities/digests checked by
the workflow; `selection.json` retains all remaining gap warnings. The durable
summary and artifact SHA-256 hashes are in
[`textual-readonly-discovery-2026-11-23.json`](../benchmarks/textual-readonly-discovery-2026-11-23.json).
No PR is merged, and no AWS deployment or paid model call is involved.
