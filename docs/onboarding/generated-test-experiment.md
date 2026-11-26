# One Textual generated-test experiment

Status: generation and original-suite controls completed on GitHub. The exact
proposal is under verification; the campaign and automatic trigger are disabled.
This experiment replaces the proposed parser-selection trial. It evaluates added
test coverage and defect detection, not test-selection speed or general agent quality.

## Fixed question and inputs

Can the product agent write a useful test for
`MarkdownTableContent._update_rows` using a coverage-gap report and public source?

Working source: `e6b3a6962a1ecd2ea20facbd2560d68a65c0fbd8` in
`SharmaKunal14/textual`. The prior passing
[GitHub enrollment](https://github.com/SharmaKunal14/textual/actions/runs/45862622090)
contains native and observed coverage with zero hits on every reported executable
body line of that method. Its declaration was executed. This is a gap in that
Linux/Python 3.14 profile, not proof that no configuration tests the method.

The agent receives the verified native coverage gap, the unchanged method source,
matching source/test paths, and access to exact revision-bound source excerpts.
It can read source, search paths, submit one Python test file, or abstain. It cannot
run commands or see the mutation, expected failure, evaluation results, or a
suggested test solution. Native conventions and the public Markdown update flow
are preferred; any private-method-only test will be disclosed as a limitation.

## Independently fixed evaluation defect

Before generation, commit `f1a9d30986616a922871020df233f883ead8dc82`
changes the row-removal selector from `self.last_row` to `self.last_row + 1`.
This intentional off-by-one mutation targets replacement of an existing row;
it is not a claim of a real upstream bug. Native tests and all other source remain
unchanged. The earlier `expand=True` change is not used or assumed to be a bug.

Only the working revision is in the model's source catalog. This document and the
defect branch are not model inputs.

## Procedure and acceptance

1. **Run unchanged controls before model approval.** With the workflow variable
   set to `controls-only`, two GitHub jobs run the existing full native suite
   with its locked dependencies on working and defective source. Preserve test
   identities, outcomes, coverage, package profiles, commit IDs and timing. These
   jobs receive no model credentials and include no generated test. The generation
   job is skipped, so this step cannot make model calls.
2. **Generate once on GitHub after approval.** Reuse the existing regular Responses API transport,
   durable ledger and four-call bounds. Save accepted actions, source observations,
   the exact proposed file, its hash, token accounting and model/tool elapsed time.
   This stage never imports Textual or executes generated code. Syntax parsing is
   only an initial check, not a security or semantic review.
   The control jobs are skipped during generation, avoiding duplicate full runs.
3. **Review the unedited proposal.** Check that assertions express the intended
   behavior, the test really exercises the target, and it does not skip, xfail,
   patch the target, manipulate coverage, or access external services or secrets.
   Unsafe or invalid output is a negative result, not automatically repaired.
4. **Verify the reviewed proposal on GitHub.** Commit its exact bytes on an
   unmerged experiment branch and bind them to the generation artifact hash. Run
   the test alone on working and defective source, with independent coverage and
   JUnit reports. Also run the surrounding existing Markdown tests on working
   source. Isolated-test coverage must show execution of the method body; combined
   coverage from unrelated tests does not establish this. Model credentials are
   absent. There is no automatic model retry or repair.
5. **Report the actual result.** A useful detection result requires a passing test
   on working source, a meaningful assertion failure on the fixed mutation, and
   no original-suite failure on that mutation. Compare identical original test
   identities and profiles. If the original suite already detects it, claim no
   incremental detection. Include actual GitHub job/trigger-to-result times,
   generation/tool time, token usage and estimated spend; do not call this a CI
   speedup. Record any human/Codex edits separately from unedited agent performance.

Generation and reviewed-test execution are separate runs because arbitrary model
code must be inspected first. Report this review delay separately; do not subtract
it and describe the experiment as an autonomous end-to-end workflow. One chosen
method and one artificial defect cannot establish general effectiveness.

## Spend and execution controls

The existing campaign `textual-public-20261123` is disabled. Its seven prior
reservations total US$0.63. The earlier one-investigation approval was consumed;
it is not reused for this experiment. Proposed new allowance: one investigation,
at most four calls, each reserving 5,000 input and 1,000 output tokens, for at most
US$0.36 additional reservations within the original US$5 ceiling. Existing
reservations remain intact. No reset, refunds, retries or Codex authentication.

The current standard model rates are US$8 input and US$40 output per million
tokens; the reservation retains the higher US$10 input rate. Revalidate the
[official pricing](https://developers.openai.com/api/docs/pricing) before activation.
The ledger's per-call token counter rejects requests exceeding the allowance.
Exhaustion, malformed output or timeout stops generation and is reported.

After explicit approval, update only the existing campaign to permit eleven
total reservations, three investigations, 55,000 reserved input and 11,000 output
tokens, and a cumulative US$0.99 reservation cap. Set
`SMARTCI_TEXTUAL_GENERATION_TRIAL=generate-one` for the exact reviewed tool branch
and trigger one PR event. The workflow disables the campaign afterward without
erasing reservations; disable the workflow variable after that run as well.
The later reviewed-test jobs use no model key and need no paid-call activation.

The additional one-investigation approval was received on 2026-11-27 (Sydney).
Generation consumed all four new reservations, then disabled the campaign. No
new call allowance remains in this experiment. `verify-one` enables only the two
reviewed-test jobs; neither full controls nor model generation are repeated.

## Recorded results so far

[Original-suite control run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45875657293):
working and defective source each produced 3,460 passes, seven identical
skip/expected-failure outcomes, and zero failures. All 3,467 identities and native
package profiles matched. Both runs still recorded zero hits on the eight
reported executable body lines. Each job took 352 seconds, or 354 seconds from
workflow creation to completion. The original suite missed this specific defect.
See the [control record](../benchmarks/textual-generated-test-controls-2026-11-27.json).

[Generation run](https://github.com/SharmaKunal14/smart-ci/actions/runs/45876697306):
the agent read two unchanged implementation excerpts and one native test excerpt,
then submitted one test. Four live calls consumed 10,531 input and 560 output
tokens; the standard uncached usage estimate is US$0.106648, not a provider invoice.
US$0.36 remains reserved; the cumulative ledger has eleven reservations totaling
US$0.99 and is disabled. Model/tool time was 32.180 seconds; preparation plus
model/tools was 35.897 seconds. These internal GitHub timings exclude runner setup;
the final report will include the entire generation job as well.

The [exact proposal and transcript](../benchmarks/textual-generated-test-proposal-2026-11-27.json)
are preserved. [Textual PR #16](https://github.com/SharmaKunal14/textual/pull/16)
contains its unedited bytes, committed as
`181d67627cfbb89a4be69b2d9923e307f2d6fcd3`, with SHA-256
`8be235aa45b8ed68d0351207d423a486a345b5309e5ab82ae161d628ad6aa8d6`.
The test uses public `Markdown.update` and `Markdown.append`, with private widget
state/tooltip assertions. Review found no external I/O, mocking, skipping, or
changes to the method under test. This review is not a passing execution result.

No AWS, merges, changes to production selection, or weakened full-suite fallback.
Local mocked tests verify the experiment's plumbing only; they are not model
effectiveness or performance evidence.
