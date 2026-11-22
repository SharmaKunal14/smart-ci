# Agent-assisted dependency investigation prototype

The product boundary is a reusable investigation engine, not Textual. Textual is
the first evaluation adapter. This increment implements offline orchestration;
it does not demonstrate that an LLM understands dependencies or improves selection.
No remote provider, credential lookup, paid call, AWS resource or merge is enabled.

## Flow and authority

1. Supply revision-bound graphs, inventory, source digests, changes and protected
   policy in `smartci.investigation-input.v1`. These are trusted collector inputs,
   not assertions supplied by a model. Their digest binds the investigation.
2. A provider chooses `search_paths`, `inspect`, `query_graph`, `propose`,
   `unresolved` or `finish` from the preceding observation. The shipped provider
   is a **rule-driven mock**: it inspects configured locations and submits up to
   two explicit import facts from each result. It is not an LLM simulation.
3. The broker accepts only paths in the source catalog and exact base/head object
   IDs. It reads Git blobs with bounded commands and verifies content hashes. It
   never executes repository source, model-supplied commands or arbitrary tools.
   Inspection returns structural facts, not source excerpts; private-source
   upload is not implemented. Repository comments cannot expand tool authority.
4. An evidence adapter verifies positive claims. The first adapter recognizes
   explicit absolute Python imports resolving to exactly one local module under
   configured roots. Relative/dynamic imports, plugins, subprocesses, resources
   and attributes are unsupported. A real literal import establishes a possible
   relationship, not its exclusive ownership or necessity during every test.
5. Only matching broker-generated observations can create accepted edges. Record
   source hash, revision, line, verifier, original graph status and graph version.
   The accepted graph preserves all old edges, completeness flags and test maps.
   It is not an automatic promotion mechanism or a signed trust attestation.
6. The existing deterministic selector consumes that additive graph. It preserves
   baseline tests, must-run policy and independent full execution. Unknown issues,
   rejected actions, duplicate loops and exhaustion cannot authorize omissions.
   An earlier full-run decision remains full with its original fallback reasons.

The report includes the baseline and final selection, accepted evidence, unresolved
issues, tool trace, termination reason and canonical digests. Replaying identical
accepted inputs produces the same selection. A live model may produce different
proposals; deterministic selection does not make model generation deterministic.

## Bounds and limitations

Default limits are 24 actions, 1 MiB of source reads, 256 KiB of responses and a
60-second loop deadline. Each source blob is at most 256 KiB; facts/search results
are capped at 64 with explicit truncation. Git operations have 20-second timeouts.
The loop deadline is checked between operations; it cannot interrupt an arbitrary
in-process provider. Only offline providers are shipped. Any later network provider
must implement its own bounded transport deadline and reserve spend before calls.

The engine is language-neutral; the first verifier supports a narrow Python scope.
Further adapters must independently implement and test their evidence semantics.
Valid JSON, another agent's agreement, a passing probe and an unobserved runtime
edge are not proof of completeness. Existing unknowns cannot be dismissed by this
prototype. In particular, additive evidence cannot reduce a Textual plan that
already falls back to everything. Finer dependency semantics would need separate
validation against the same native profile and held-out regressions.

## Verification

`smartci schema investigation-input` exports the input contract. With a collected
input artifact and its original repository objects available:

```sh
uv run smartci investigate --inputs /path/to/investigation-input.json \
  --repo /path/to/repository --module-root src \
  --focus src/example.py --output /path/to/investigation.json
```

Replace `src/example.py` with an actual path in the artifact. This command is
offline and does not execute tests. `make check` covers forged source/evidence,
cross-repository revisions, traversal, unauthorized actions, loops/budgets,
must-run preservation, immutable inputs, deterministic replay and additive
selection. These are plumbing/safety checks, not model effectiveness measurements.

The Textual harness `examples/textual/agent_compare.py` automatically chooses
changed paths followed by unresolved source paths (at most four), inspects both
revisions and repeats the mock loop. It preserves native discovery, dependencies,
coverage, test flags and independent full fallback. Compare three jobs on the
same real PR: native, current static Smart CI, and assisted replay. Report their
complete GitHub timings, case identities/outcomes, failures missed, fallbacks and
runner-seconds. A single regression and replay do not establish broad performance.

## Proposed live evaluation budget — not authorized

Propose a **US$5 total ceiling**, not a prediction of cost or authorization. Start
with two real Textual changes and three trials each: at most six investigations,
four model calls each (24 total, including retries), 120,000 aggregate input tokens
and 24,000 output tokens. No recursive agent spawning or test execution tools.
Use the same inspection tools and evidence for fixed and adaptive investigators.
Every call must fit the remaining token and dollar reservation at freshly verified
provider/model prices, including all billable reasoning/output. Stop when a limit
is reached; never auto-top-up. If the selected model cannot fit, reduce the trial
scope explicitly or leave live evaluation disabled. The dollar ceiling takes
precedence over reaching six investigations.

Before enabling calls: agree on that ceiling and provider/model/data routing;
implement usage reservation, timeouts, error accounting and a kill switch; verify
rates and run an admission-only test. Token caps and estimated cost alone are not
a billing cap. Current approved model spend remains **US$0**. GitHub runner usage
is separate and must be reported from the completed workflows.
