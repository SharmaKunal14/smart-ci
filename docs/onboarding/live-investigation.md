# Budgeted live investigation

The approved experiment has a **US$5 total ceiling, 24 calls and six investigations**.
This is a small evaluation of an optional provider, not permission to enable an
unbounded production agent. Replay remains the default CLI provider. No model can
waive missing evidence, remove existing dependencies, clear unknowns or suppress
required tests. The Textual graph currently still requires full execution.

## Admission and accounting

The initial model is `gpt-6.2-astra`, standard service, low reasoning effort, with
at most 5,000 input and 1,000 output tokens per call. Output limits include reasoning.
On 22 November 2026 at 19:40 UTC, [official pricing](https://developers.openai.com/api/docs/pricing)
listed short-context standard input at US$8 and output at US$40 per million tokens.
We reserve the higher US$10 input rate to cover even a 30-minute cache write.
Each admitted attempt permanently reserves US$0.09; all 24 reserve US$2.16. The
US$5 ceiling remains an additional admission check. This excludes GitHub runner
usage, taxes and other users of the API account. It is not a provider billing cap.

The rate card expires after 24 hours. `budget.json` lives on one dedicated Git
branch, outside ephemeral runners. The CLI cannot initialize or reset that ledger.
Each investigation has at most four unique slots, keyed by input identity and
trial. The aggregate limits are 120,000 input and 24,000 output tokens. Conditional
GitHub Contents API writes must succeed before token counting or inference.
Stale updates, lost acknowledgments, missing state, invalid usage, timeouts and
reruns never release or retry a reservation. Invalid reported usage disables the
campaign. Usage is recorded separately; reserved dollars are not an invoice.

There are no automatic HTTP retries, redirects or alternative endpoints. A token
count request must confirm the exact input fits before inference. The generation
request sets `max_output_tokens=1000`, no hosted tools, `store=false`, and the
standard service tier. Explicit caching with no breakpoints requests no cache
writes. `SMARTCI_DISABLE_MODEL_CALLS=1` blocks local admission; setting the shared
ledger's `enabled` to false blocks all future admission. Already-submitted calls
may still finish and be billed. A repository administrator can edit or reset a
Git branch: this prototype does not provide a tamper-proof enterprise spend ledger.

## Data and credentials

Only the global `api.openai.com` endpoint is supported. This does **not** guarantee
regional residency. Only verified public GitHub base/head commits are allowed in
the first live pilot. Source reads use immutable Git objects, content hashes and
`--no-replace-objects`. Excerpts require `allow_source_excerpts=true` in the trusted
input policy and the explicit CLI scope `public-github-global-openai`.

Repository metadata, tool observations and permitted source excerpts go to the
provider. Raw excerpts and reasoning content are excluded from the audit trace.
`store=false` is not zero retention: [OpenAI's data controls](https://developers.openai.com/api/docs/guides/your-data)
describe default abuse-monitoring retention of up to 30 days and no API training
by default. Private enterprise code needs a separate routing/retention design.

`OPENAI_API_KEY` is an Actions secret, passed only to the live step. Credentials
travel to isolated HTTP workers over stdin, never argv or logs. They are not
available while installing tools or executing application tests. The model has
no shell, test-execution or network tool. GitHub ledger writes require
`contents: write`; GitHub's token permission is repository-wide, while this adapter
constrains writes to `budget.json` on the configured `codex/model-budget-*` branch.

## Verification and evaluation

The `Model budget controls` PR workflow first uses a **disabled, empty probe ledger**
on `codex/model-budget-disabled-probe`. It accepts one conditional update, rejects
a second update using the stale SHA, re-reads the persisted state and verifies
disabled admission. No OpenAI secret is supplied to this probe. The uploaded
`model-budget-probe-*` artifact records actual HTTP statuses and zero model calls.

Safety tests cover aggregate caps, duplicate invocation, stale pricing, malformed
responses, refusals, missing/excess usage, source permission, redaction, timeout
and fallback preservation. These tests use transport doubles. They are not evidence
of live-model quality. Full verification is `make check` and `uv build`; the hosted
PR run is the reportable result.

Once those controls pass, the initial live trial must use pinned inputs from a real
Textual PR. Preserve the input/report hashes, run URL, model attempts, tokens,
reservations, accepted new versus already-known edges, unresolved issues and
baseline/final plan. Compare a replay given the same inputs. Model generation is
not deterministic; final selection from identical accepted evidence is.

The current verifier only accepts explicit Python imports already supported by
static analysis. A live model may therefore add no useful information. Even a valid
new positive edge cannot justify removing tests from a plan that already requires
everything. No full-suite rerun or speedup claim is justified without a materially
different, mechanically supported plan. Provider effectiveness and actual GitHub
end-to-end savings remain separate, unmet acceptance criteria.

The first [hosted control check](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062445146)
recorded HTTP 200 for the accepted write, 409 for the stale write and rejected
admission while disabled. The corresponding [safety run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062445152)
passed 540 tests, formatting, lint, types and both package builds.

The live job is separately gated by the repository Actions variable
`SMARTCI_LIVE_CAMPAIGN=textual-public-20261123` and the shared ledger. It verifies
the SHA-256 of the downloaded input from Textual PR #11/run 45058699772 before
changing only the public source-excerpt permission. It executes no Textual code.
The first trial is fixed to slot group 1; rerunning the workflow cannot obtain a
new investigation identity. Its upload includes `summary.json`, live/replay audits
and the exact permitted input. Later trials require a deliberate harness change;
the six-investigation allowance is a ceiling, not a quota to spend.

## First live result, 23 November 2026

[Smart CI PR #12](https://github.com/SharmaKunal14/smart-ci/pull/12) ran the optional
provider in [GitHub run 45062767011](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062767011).
The model made three calls: inspect the changed parser, query its graph, then
finish. Those calls reported 5,835 input and 111 output tokens. Standard uncached
generation pricing estimates **US$0.05112**, not an invoice or total account bill.
The ledger retains **US$0.27** in reservations. Both the workflow variable and the
shared campaign are now disabled; reservations were not reset or refunded.

The live investigator accepted **zero claims and zero new edges**. The bounded
replay accepted two already-known imports and also added zero edges. Both retained
all 14 unresolved issues and a full 251-file plan with `INCOMPLETE_EVIDENCE`.
The live final test list exactly matches its baseline. No Textual tests executed
in this investigation run; the source evidence came from the earlier real PR run.
There is no new regression-recall or end-to-end test-saving measurement here.

The live job took 62 runner-seconds. The disabled control probe took another 17;
the complete workflow took 85 seconds from trigger to completion. These are
investigation/control overhead figures, not a substitute for the native CI
baseline. [Hosted safety verification](https://github.com/SharmaKunal14/smart-ci/actions/runs/45062767010)
passed all **542 tests**, formatting, lint, strict typing and both package builds.

The [evidence record](../benchmarks/textual-live-investigation-2026-11-23.json)
binds revisions, input/report hashes, model usage, actions and job URLs. To verify,
open the linked workflow, download `model-live-trial-1`, and inspect `summary.json`
and `live.json`. The separate `model-budget-probe-1` records real conditional-write
rejection. Do not re-enable or reset the ledger merely to repeat a completed trial.

This establishes that the bounded live tool loop works. It does **not** establish
that an LLM improves Smart CI. The current verifier only recognizes supported
absolute imports, and additive edges cannot narrow an existing full fallback.
The next meaningful experiment needs a general, mechanically verified dependency
scope that addresses an actual unresolved pattern; prompt changes or more model
votes cannot supply that proof. One short trial also cannot characterize model
quality across repositories. The broader time-and-resource savings goal is unmet.
