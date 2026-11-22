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

The bounded hosted check compares the old and new collectors on the same Textual
PR base/head and locked native environment. It checks inventory identities,
source hashes, import and edge digests, and the exact diagnostic difference.
Both plans must still require full execution. This is a discovery diagnostic,
not a test-time benchmark or evidence of CI savings. Hosted results will be
recorded after the run finishes; they are not presumed from these tests.
