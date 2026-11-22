# Fixture scopes and lower-overhead runtime observation

The previous Textual experiment attributed collection and fixture setup to every
test. This opt-in extension separates temporal scopes so that a function fixture
used by the parser tests can be distinguished from a session fixture. It remains
advisory: scope does not establish exclusive ownership of side effects, and no
runtime report is accepted as a production selection plan.

## What changed

- Public pytest collection and fixture-setup wrappers record the active scope.
  Function, class and module scopes retain a tracked test-file owner; package
  fixtures retain their package and session fixtures retain the whole session.
  Cached fixtures are never assigned only to the first consuming test.
- The observer does not request, wrap, reorder or finalize application fixtures.
  Teardown and unknown owners remain shared. Background work and cross-test side
  effects remain unproven; temporal attribution is not dependency completeness.
- An optional Python monitoring engine records starts, resumptions and generator
  throws. It reserves only a free tool ID, retains native coverage/profiling tools,
  never calls the global `restart_events`, and cleans up only its own ID. Missing
  slots or replaced instrumentation become explicit diagnostics.
- Detailed contexts use schema `smartci.runtime-observation.v2`. The original
  profile engine and v1 report remain available. Both always set `complete` and
  `omission_authorized` to false. No parameter values, exception contents, process
  arguments or external file paths are added to the report.

The APIs used are documented in [pytest's hook reference](https://docs.pytest.org/en/stable/reference/reference.html)
and [Python's monitoring reference](https://docs.python.org/3.14/library/sys.monitoring.html).

## Evaluation

The `examples/textual/benchmark.py --mode observe-scoped` path runs the same full
native tests, coverage and locked dependency environment, with these observer
options appended:

```sh
--smartci-observation-engine monitoring --smartci-observation-contexts
```

It does not change the native control or execute a proposed subset. Compare all
case identities, outcomes and skips in the two GitHub JUnit artifacts before
interpreting observations. Compare whole-job and trigger-to-result time, including
observer installation and artifact publication. Do not present observer speed as
selective-CI savings.

The assessment accepts both report versions, validates their digests and source
revisions, and expands recorded scopes conservatively. Unknown metadata expands
to every test file. Even a narrower candidate list is not an executable plan.

The 14 static gaps, path-loaded example scope, dynamic resources, plugin behavior
and external/background execution still require supported contracts before the
production selector can omit tests. This extension does not waive any of them.

Hosted results will be recorded after the paired run finishes. No live performance
claim is made by the implementation alone.
