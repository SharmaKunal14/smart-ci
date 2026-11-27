# One Textual generated-test experiment

**Retired:** the user replaced generation/repair with
[deterministic coverage-gap reporting](coverage-gaps.md). The workflow jobs are
hard-disabled on the reporting branch, all model campaigns remain disabled, and
prior approvals must not be reused. This document preserves historical evidence.

Both the original attempt and the one approved repair were negative. The original
test failed on working and defective source. The revised test failed on working
source before executing `_update_rows`, so its held-out evaluation was not
admitted. All approved repair calls are consumed; the campaign and experiment
triggers are disabled. This evaluates added coverage and defect detection, not
test-selection speed or general agent quality.

## Fixed scope and provenance

The target is `MarkdownTableContent._update_rows` at working commit
`e6b3a6962a1ecd2ea20facbd2560d68a65c0fbd8` in `SharmaKunal14/textual`.
The passing [enrollment run](https://github.com/SharmaKunal14/textual/actions/runs/45862622090)
and new original-suite controls recorded zero hits on all eight reported
executable body lines. The declaration was executed. This is a gap for that
Linux/Python 3.14 native profile, not universal absence of tests.

Before generation, [Textual PR #15](https://github.com/SharmaKunal14/textual/pull/15)
fixed an independent artificial defect at
`f1a9d30986616a922871020df233f883ead8dc82`: row removal uses `self.last_row + 1`
instead of `self.last_row`. All existing tests and other source are unchanged.
The mutation is not a claim of a real upstream bug. It remains excluded from all
model input. The earlier `expand=True` change is not used or presumed to be a bug.

[Textual PR #16](https://github.com/SharmaKunal14/textual/pull/16) contains the
original model output with no human/Codex edits or formatting changes, at commit
`181d67627cfbb89a4be69b2d9923e307f2d6fcd3`. Its file SHA-256 is
`8be235aa45b8ed68d0351207d423a486a345b5309e5ab82ae161d628ad6aa8d6`.
The [proposal, accepted actions and source transcript](../benchmarks/textual-generated-test-proposal-2026-11-27.json)
are preserved separately from any future revision. All experiment PRs are unmerged.

## Verified first-attempt GitHub results

| Stage | Result | Job time | Workflow creation to result |
| --- | --- | ---: | ---: |
| Original suite, working source | 3,460 passed; 7 skip/expected-failure outcomes; 0 failures | 352s | 354s |
| Original suite, defect | Identical identities, outcomes and environment; defect missed | 352s | 354s |
| Agent generation | Four API calls produced one test | 81s | 84s |
| Generated test, working source | 1 assertion failure; 0/8 target-body lines executed; 42 surrounding native tests passed separately | 65s | 67s |
| Generated test, defect | Same assertion failed; 0/8 target-body lines executed | 60s | 62s |

Sources: [controls](https://github.com/SharmaKunal14/smart-ci/actions/runs/45875657293),
[generation](https://github.com/SharmaKunal14/smart-ci/actions/runs/45876697306),
[verification](https://github.com/SharmaKunal14/smart-ci/actions/runs/45877497403),
and the [reconciled result record](../benchmarks/textual-generated-test-result-2026-11-27.json).
All four native environments matched exactly, including Python 3.14.10 and locked
package versions. The generated-test and surrounding-test coverage are separate.

The generation used 10,531 input and 560 output tokens: approximately US$0.106648
at the checked standard uncached rates, not a provider invoice. Model/tool time
was 32.180s; preparation plus model/tools was 35.897s, both inside the 81s job.
The five experiment jobs consumed 910 runner seconds; wall time across the three
separately triggered stages was 889s, including approval, review and workflow
preparation. These figures exclude Smart CI's own safety-check jobs and are not
an autonomous product latency or a speedup claim.

The failure was at generated-test line 26, which required earlier row widgets to
retain their identity after a public Markdown update/append sequence. Working-run
coverage shows that the table-specific update branch was bypassed and the general
block remove/mount path ran. The saved table reference then had no earlier rows.
The assertion failure therefore did not distinguish the hidden defect.

Known: this input did not exercise `_update_rows`; preserving private widget
identity is not established by the public append contract. Unresolved: whether
the observed append-after-update behavior also reveals a separate baseline
content issue. Neither an upstream bug nor an acceptable test setup follows
merely from this identity assertion. Initial semantic review did not catch the
setup/path problem; actual execution invalidated the proposal. No test edits or
extra calls were used to turn the first attempt into a success.

## Verified repair GitHub results

The user explicitly approved one repair investigation on 27 November 2026
(Australia/Sydney). The agent received the original test, working-code failure
and zero-hit coverage report, with read-only access to the pinned public source.
The held-out mutation and defective-run results were excluded. It inspected
`Markdown.append`, the table update dispatch and test paths, then submitted a
revision on its fourth call. The complete [repair proposal and transcript](../benchmarks/textual-generated-test-repair-proposal-2026-11-27.json)
are preserved independently of the original proposal.

The revised test is frozen at Textual commit
`8954efa2d402c22be382dc3a92a7f05cab865663`, file SHA-256
`3f4db313d52e6d09b658fe48c4a16cfadb90e04da14648c8f6ebefc723cecffe`.
No human/Codex edits or formatting changes were made to either generated test.
The revision mounts a table through `Markdown.update`, then intends to call
the real private `_update_rows` method directly and verify preserved, replaced
and added row values. This is a method-level test, not verification of the
public `Markdown.append` dispatch.

| Repair stage | Result | Job time | Workflow creation to result |
| --- | --- | ---: | ---: |
| Agent repair | Four API calls produced one revision | 87s | 90s |
| Revised test, working source | 1 failure; 0/8 target-body lines executed; 42 surrounding native tests passed separately | 66s | 69s |
| Revised test, held-out defect | Not run: working-source acceptance failed | — | — |

Sources: [repair generation](https://github.com/SharmaKunal14/smart-ci/actions/runs/45887385150),
[working verification](https://github.com/SharmaKunal14/smart-ci/actions/runs/45887826034),
and the [reconciled repair result](../benchmarks/textual-generated-test-repair-result-2026-11-27.json).
The working environment exactly matched the earlier original-suite control.

The failure is `AttributeError: 'str' object has no attribute 'plain'` at revised
test line 24, called by its initial assertion at line 26. The helper assumes that
every cell tooltip is a `Content` object. The existing table composition sets
initial tooltips to `cell.plain` strings, and the widget stores that value without
conversion. The test therefore fails before calling the target. This is a
generated-test type assumption, not evidence of a baseline Textual defect. Source
review flagged the mismatch while the working job was running; CI confirmed it.
The earlier append-after-update behavior remains a separate unresolved question.

The repair used 12,385 input and 557 output tokens: **US$0.121360 estimated** at
the checked standard uncached rates, not an invoice. The US$0.36 reservation
remains charged against the campaign allowance. Model/tool time was 36.607s;
preparation plus model/tools was 44.887s within the 87s generation job. Both jobs
consumed **153 runner seconds**, including setup. Their separate trigger-to-result
times sum to 159s; actual wall time from repair workflow creation to working-job
completion was **293s**, including operator review and publication of the frozen
test. These numbers exclude Smart CI's safety-check jobs and are not autonomous
product latency. Original generation plus repair used an estimated US$0.228008.

**Conclusion:** this bounded feedback iteration did not produce a valid test,
add target coverage, or demonstrate agent value or CI savings. It does not prove
that every agentic approach will fail. The workflow was operator-orchestrated,
with source-read tools and one repair iteration; it was not an unrestricted agent
with command execution. No further repair is authorized by this allowance.

## Bounded generate/execute/inspect/revise procedure

This was one controlled repair of that first failed attempt. Steps 1–4 ran;
step 5 was correctly withheld after the working-source failure.

1. **Inspect working feedback.** The strict
   [working-feedback record](../../examples/textual/generated-test-working-feedback.json)
   contains only the original proposal, its digest, the real working-job failure
   message/location and coverage hashes/line hits. The original source hash and
   working revision are checked. Defect-run results and mutation details are not
   included. Source locations for `Markdown.update` and `Markdown.append` are
   derived from the unchanged source AST; no test solution is supplied.
2. **Revise once after paid-call approval.** Set the experiment gate to `repair-one`
   for the reviewed tool branch and trigger one PR event. The agent can read exact
   public Git source, search paths, submit a revised file, or abstain. It receives
   working feedback and must investigate its setup/assertions without assuming a
   baseline bug. The existing regular Responses API, reservation ledger and
   four-call limit apply. The generator never imports Textual or executes proposed
   code. Save the complete accepted transcript, exact output bytes, hash and costs.
3. **Review and freeze the revision.** Preserve the first proposal and commit the
   new one separately, with any human/Codex edits explicitly reported. Check its
   behavioral assertions and reject skipping, xfail, target monkeypatches, fake
   coverage, external I/O or dropping meaningful checks merely to pass. Bind the
   workflow to the immutable generated-test commit and exact file hash.
4. **Execute on working source only.** Use `verify-working`, with no model key.
   Run the generated file alone and the 42 surrounding native Markdown tests
   separately. `check_generated_test.py` requires passing generated cases without
   skips/expected failures and execution of all eight recorded target-body lines.
   A passing coverage gate does not prove assertion correctness; retain semantic
   review. Failure or inadequate assertions ends this bounded repair attempt.
5. **Inspect, then evaluate held-out source.** Only after the working gate and
   semantic review pass, trigger `verify-heldout` using the exact same frozen
   commit/file hash. The operator checks the working run and revision binding
   before enabling this stage; do not describe this review step as fully
   autonomous. The held-out result never becomes model feedback in this attempt.
   Compare against the original-suite controls already recorded; do not rerun
   them merely to improve timings or change the chosen defect.
6. **Report either outcome.** Useful detection requires a test that passes on
   working source, executes the intended body, and fails meaningfully on the
   fixed defect missed by the original suite. Preserve every revision, native
   execution result, model/tool and total CI timing, spending and manual changes.
   If this repair fails, report it; no further paid repair is authorized.

This is a single feedback iteration following the first generate/execute cycle.
Model requests have no command-execution capability; native execution is isolated
in credential-free CI jobs. The campaign is disabled after the model job, and the
trigger is closed after each admitted stage. The original `generate-one` and
combined `verify-one` runs remain reproducible from their recorded older tool
commits; the current workflow only admits the staged repair path.

## Approved repair allowance; consumed and disabled

Before approval, `textual-public-20261123` was disabled with eleven retained
reservations totaling US$0.99. Explicit approval added one investigation with four
call slots and US$0.36 of reservations. All eleven earlier records were preserved.
After the repair, the campaign is disabled with fifteen reservations totaling
US$1.35 and no remaining authorized call slots. All three live experiment
variables are `disabled`. Resuming the goal is not new paid-call authorization.

Approved: **one repair investigation, at most four calls, US$0.36 additional
reservations within the original US$5 ceiling**. Each call reserves at most 5,000
input and 1,000 output tokens. The four-call total is 20,000 input and 4,000 output
tokens. The source/tool loop has a 120s check and the containing model step a
four-minute timeout; network failures and uncertain calls are not retried or
refunded. Invalid output or exhaustion stops the attempt.

After explicit approval, [official pricing](https://developers.openai.com/api/docs/pricing)
was checked at 2026-11-26 19:56 UTC (27 November in Sydney). A conditional ledger
update allowed fifteen total reservations, four investigations,
75,000 reserved input and 15,000 output tokens, with a cumulative US$1.35 reservation
cap, retaining every old reservation. The reservation uses US$10 input and US$40 output
per million tokens; the last checked standard uncached input rate was US$8. Do not
activate if current rates exceed the reserved rates. No new provider or Codex
authentication is introduced.

Production selection remains deterministic, with conservative full fallback.
No AWS deployment or merges. Mocked checks validate control behavior only, not
model effectiveness or performance. Even a successful repair of this chosen
method/defect would not establish safe test omission or CI speed savings.
