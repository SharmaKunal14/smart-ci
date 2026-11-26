# Agent-assisted dependency investigation prototype

The product boundary is a reusable investigation engine, not Textual. Textual is
the first evaluation adapter. Offline orchestration is verified. The optional
[budgeted live provider](live-investigation.md) has completed one hosted trial;
it added no new edges and does not demonstrate improved selection.
Replay remains the default. No AWS resource or merge is enabled.

## Flow and authority

1. Supply revision-bound graphs, inventory, source digests, changes and protected
   policy in `smartci.investigation-input.v1`. These are trusted collector inputs,
   not assertions supplied by a model. Their digest binds the investigation.
2. A provider chooses `search_paths`, `inspect`, `query_graph`, `propose`,
   `unresolved` or `finish` from the preceding observation. The shipped provider
   defaults to a **rule-driven mock**: it inspects configured locations and submits
   up to two explicit import facts from each result. The optional diagnostic
   replay routes process gaps to a registered process inspector. Neither replay
   measures LLM reasoning or quality.
3. The broker accepts only paths in the source catalog and exact base/head object
   IDs. It reads Git blobs with bounded commands and verifies content hashes. It
   never executes repository source, model-supplied commands or arbitrary tools.
   Inspection returns structural facts. The optional `read_source` action requires
   explicit source-excerpt policy permission. The initial live path verifies public
   GitHub commit availability; private-source upload is unsupported. Repository
   comments cannot expand tool authority.
4. An evidence adapter verifies positive claims. The first adapter recognizes
   explicit absolute Python imports resolving to exactly one local module under
   configured roots. A second, opt-in adapter recognizes bounded file-anchored
   Python script arguments in process calls; see [process evidence](process-evidence.md).
   Both are positive evidence only. General dynamic imports, plugin behavior,
   process side effects, resources and attributes remain unresolved. A literal import establishes a possible
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
in-process provider. The optional live provider uses isolated HTTP workers with
20-second wall-clock limits per request and persistent spend reservations. The
loop deadline is checked between operations, not a process-wide hard deadline.

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

## Approved ceiling and current live status

The user approved a **US$5 total ceiling**, at most 24 calls and six investigations on
23 November 2026. This is a ceiling, not a prediction of cost. Start
with two real Textual changes and three trials each: at most six investigations,
four model calls each (24 total, including retries), 120,000 aggregate input tokens
and 24,000 output tokens. No recursive agent spawning or test execution tools.
Use the same inspection tools and evidence for fixed and adaptive investigators.
Every call must fit the remaining token and dollar reservation at freshly verified
provider/model prices, including all billable reasoning/output. Stop when a limit
is reached; never auto-top-up. If the selected model cannot fit, reduce the trial
scope explicitly or leave live evaluation disabled. The dollar ceiling takes
precedence over reaching six investigations.

Before enabling calls: verify provider/model/data routing;
implement usage reservation, timeouts, error accounting and a kill switch; verify
rates and run an admission-only test. Token caps and estimated cost alone are not
a billing cap. The approved ceiling is **US$5**. A subsequent live trial made three
generation calls (US$0.05112 usage estimate, US$0.27 retained reservation); the
campaign is disabled after that trial. See the [live results](live-investigation.md#first-live-result-23-november-2026).
GitHub runner usage is separate and is reported from the completed workflows.

## Real GitHub comparison, 23 November 2026

[Smart CI PR #11](https://github.com/SharmaKunal14/smart-ci/pull/11) implements the
prototype at `bcbf54de3e98b991db9a8c312db492ed6a73b6d8`.
Its [hosted safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45058488501)
passed all 499 tests, formatting, lint, type checks and wheel/source builds.

[Textual PR #11](https://github.com/SharmaKunal14/textual/pull/11) changes only one
line of the historical terminal-key parser regression. The dedicated base contains
the workflow. Its [first-attempt comparison](https://github.com/SharmaKunal14/textual/actions/runs/45058699772)
finished with intentional native test failures in every arm:

| Approach | Trigger to job completion | Runner time | Planning | Native test process |
| --- | ---: | ---: | ---: | ---: |
| Native full suite | 360 s | 357 s | 0 s | 309.44 s |
| Current static Smart CI | 472 s | 470 s | 53.84 s | 359.28 s |
| Smart CI + offline investigation replay | 401 s | 399 s | 36.65 s | 306.75 s |

Every arm executed all **3,467 cases / 251 test files**. Case identities, outcomes
and skip details matched; each caught the same extended-key parser failure. Zero
failures were missed, but zero tests were omitted, so this is not evidence that
omission is safe. Both Smart CI arms fell back on this one PR: 1/1 each, with
`INCOMPLETE_EVIDENCE`. The replay accepted 14 claims that were already recorded,
added **zero new edges**, retained **14 unresolved issues**, and reproduced the
same entire investigation report on repeat. Inventory/environment identities
also matched the static collector's hosted artifacts.

The replay was **41 seconds slower than native CI**. Its 71-second advantage over
the static arm cannot be attributed to agent reasoning: no model was called and
the static arm's native test process alone varied by about 53 seconds. This is one
paired experiment, not a robust performance estimate. Total measurement compute
was 1,226 runner-seconds across the three jobs. No selective savings or LLM benefit
was demonstrated. A second comparison is not justified solely to seek a better
timing; live model evaluation is a separate pending experiment.

The [durable evidence record](../benchmarks/textual-agent-replay-2026-11-23.json)
contains exact revisions, job URLs, case failure IDs, hashes and timing boundaries.
The benchmark clock includes queue/setup/planning/tests/artifact upload through
job completion; report generation after artifact download is not included.
`examples/textual/compare_agent.py` checks complete first-attempt GitHub provenance,
case-level parity and report integrity, rejecting incomplete or mismatched results.
