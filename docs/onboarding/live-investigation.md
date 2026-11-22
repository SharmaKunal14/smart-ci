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
