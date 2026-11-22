# Python discovery improvements: Textual follow-up

## Scope

This change fixes supported static-resolution cases. It does not authorize
omissions from incomplete evidence and does not claim that Textual now has a
complete dependency graph. Selection policy, native tests, skips, coverage and
full-suite fallback are unchanged.

Implementation: `d8840222d9bf8d5ef023bf3be30d66c4729c6353`,
[Smart CI PR #5](https://github.com/SharmaKunal14/smart-ci/pull/5).

The resolver now:

- Retains qualified names for helpers beneath a regular test package, including
  intermediate namespace directories, instead of incorrectly treating every
  helper as a top-level module.
- Resolves namespace directories beneath tracked regular packages while keeping
  package-initializer edges. Root namespaces without native search-location
  evidence remain unsupported. Explicit package-path manipulation and a module
  used as a package parent produce gaps.
- Recognizes literal relative `importlib.import_module` calls with a literal
  package argument. Variable names, excessive relative levels and unsupported
  argument forms remain opaque.
- Recognizes closed lazy-export dispatch: a literal name comparison, a literal
  import and an immediately returned imported symbol. A literal distribution
  version lookup is also supported. Unknown code, computed imports, additional
  statements and dynamic diagnostics retain the attribute-hook gap. Every
  recognized import still becomes an ordinary dependency edge.
- Clears analysis state between invocations, so removing an initializer cannot
  leave stale namespace evidence.

The implementation digest changes automatically, invalidating older snapshots.
These are bounded static rules, not a formal proof for arbitrary Python runtime
behaviour, monkeypatching or external inputs.

## Verification

[Hosted safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45027761419)
passed 303 tests, formatting, lint, typing and package build. Added tests cover
helper resolution, namespace ordering, package-path mutations, missing
initializers, literal relative imports, deterministic output and rejected
dynamic variants of lazy exports.

The real comparisons replay exactly the original source-only regressions:

- [Textual PR #4](https://github.com/SharmaKunal14/textual/pull/4): Markdown
  context regression; [run](https://github.com/SharmaKunal14/textual/actions/runs/45027800929).
- [Textual PR #5](https://github.com/SharmaKunal14/textual/pull/5): terminal-key
  parser regression; [run](https://github.com/SharmaKunal14/textual/actions/runs/45027804406).

Only the pinned planner changes in the experiment base. Native tests and their
dependencies are unchanged. Each PR compares its native full command with the
Smart CI path on separate GitHub runners at the same head revision. Inspect
`selection.json`, both compatibility reports, `execution.json` and `junit.xml`
in the run artifacts. End-to-end time includes queueing from workflow creation,
checkout, environment installation, planning, testing and artifact publication.

## GitHub result: selective-execution objective not achieved

| Comparison | Native trigger to result | Smart CI trigger to result | Slowdown |
|---|---:|---:|---:|
| Markdown PR #4 | 336 s (5m 36s) | 408 s (6m 48s) | 72 s |
| Parser PR #5 | 358 s (5m 58s) | 460 s (7m 40s) | 102 s |

Entire job durations were 334 versus 405 seconds for Markdown, and 355 versus
458 seconds for the parser. Planning took 35.95 and 51.89 seconds respectively.
The remaining timing differences include setup and native-test runtime variance;
the whole slowdown must not be attributed to graph analysis. These are single
observations of different scenarios, not repeat-run medians.

Both comparisons retained the same 3,467 case identities and native skip
identities. Each produced one identical failing case: the Markdown theme-switch
snapshot and the parser's multi-key sequence regression. No observed failures
were omitted, but this was **full fallback**, not evidence of selective safety.

Gaps fell from 30 to 14 per snapshot. The eleven namespace gaps, four unresolved
local-helper imports and one metadata-only lazy attribute gap were resolved.
The remaining two custom import paths, two attribute hooks, two dynamic-code
sites, four dynamic imports, two unresolved imports, unreviewed plugin set and
unsupported module name still make the graph incomplete. All 251 test files
were selected with `INCOMPLETE_EVIDENCE`; no safety gap was suppressed.

Therefore this is a verified partial implementation, not completion of the
requested Textual subset support. Resolving the remaining runtime behaviour
requires additional collector capabilities and evidence. The current native
profile cannot be labelled safe for omissions on these results. No further
benchmark retries were launched to search for a favourable timing sample.

Raw GitHub evidence is retained under ignored `demo-output/textual-discovery/`;
the checked summary is `docs/benchmarks/textual-discovery-2026-11-23.json`.

## Agentic design boundary

An agent can inspect a repository, propose collector extensions, generate
adversarial fixtures, investigate failed replays and explain decisions. A model
proposal is not completeness evidence. Model agreement, repeated reflection or
one successful test run does not establish that an omitted test cannot fail.

The deterministic decision should consume validated, revision-bound evidence.
An advisory model may propose extra edges conservatively; it cannot remove
edges, mark unknown analysis complete or suppress a fallback. A collector change
requires executable checks and full-suite comparisons. This keeps PR planning
reproducible while permitting agents around onboarding and maintenance.

No paid model invocation or agent service was added by this change. A universal
repository scanner remains an aspiration, not an implemented or verified claim.
The unresolved work is bounding runtime-loaded application code, plugin effects
and resource relationships without silently assuming they are irrelevant.

## Deployment

No AWS deployment is required. Changes are published on isolated branches; PRs
remain unmerged. The deliberately regressed application PRs must remain red when
the native regression tests fail. A safe subset and a measured end-to-end
improvement are separate acceptance requirements; neither follows merely from
reducing the number of collector gaps.
