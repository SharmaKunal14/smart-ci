# Runtime candidate evaluation

This experiment asks whether function-entry observations can identify a useful
candidate for Textual's real Markdown regression. It does **not** authorize
production omissions. The deterministic production selector is unchanged; the
independent native full job remains required. No model calls or AWS resources.

## Focused three-arm comparison

Use one real Markdown regression and one passing enrollment. Compare (1) the
unchanged full suite, (2) the deterministic runtime candidate, and (3) that same
candidate plus a bounded live investigation. Both Smart CI arms start with the
same source revisions, runtime map, mandatory-process rules and available source
inspection tools. Verified positive facts may add tests to the agent arm; a model
cannot remove observed callers or promote evidence to production skip authority.
The final candidate is a deterministic function of the initial evidence and
accepted facts. Model generation itself is not deterministic.

The incremental agent result is added facts, changed targets, missed native
failures, model/tool time and complete CI time relative to the non-agent arm. A
zero-change result is negative evidence for the agent's usefulness on this case.
Runtime selection savings alone are not a model benefit, and replay is not a live
agent. This is an addition-only experiment: it tests whether an agent finds
relationships missing from the initial map, not whether it can beat that map by
removing dependencies. Report this limitation explicitly.

Proposed live scope: one investigation, at most four calls, at most 5,000 input
and 1,000 output tokens per call, regular OpenAI API with public Textual source
only. Reuse the existing ledger without resetting its three reservations. At its
recorded conservative rates, at most US$0.36 additional reservation fits within
the original US$5 campaign ceiling. Pricing must be reverified before admission.
The campaign remains disabled until explicit reactivation approval. Model
credentials must exist only in the investigation step and never in test execution.
The existing key is in Smart CI's repository, not the Textual fork; run the three
measurement arms in one Smart CI evaluation workflow against the same pinned real
Textual PR. Report that workflow's full trigger-to-job times and distinguish them
from automatic Textual-PR trigger latency, which this arrangement does not measure.

## Starting point and deliverables

File-level import reachability reaches almost the entire Textual suite. The
revision-bound change-scope tool distinguishes method-body changes from module
initialization changes, but dynamic dispatch prevents claiming a complete call
graph. Runtime observations supply positive evidence; absence is not independence.

The experimental builder validates the exact passing base tree, observer
implementation, observation integrity and completeness diagnostics. For edits
limited to existing function bodies it joins their old entry locations to
recorded test/fixture contexts. Unknown/shared execution contexts expand to all
tests. Tests that attempted child processes are retained without logging process
arguments. Unsupported changes and missing process attribution require full
fallback. Must-run inputs can only add known tests.

Source reads, unobserved changed functions and background work remain explicit
uncertainties. They are **not resolved** by this heuristic. Its output uses a
separate schema that cannot validate as a production selection report or snapshot.
An experimental subset is safe to evaluate only because the full native suite
still runs independently. Passing this comparison would not prove future safety.

## GitHub procedure

1. Pin the reviewed Smart CI commit in `runtime-candidate-workflow.yml`. Use an
   isolated fork base branch, with identical application/tests/lockfile/native
   coverage options. The workflow has two bounded jobs, read-only permissions,
   no credentials in test steps, and seven-day artifact retention.
2. Create an enrollment PR against `codex/runtime-candidate-base`. Both native
   and instrumented paths run everything. Require matching case identities,
   outcomes and skip reasons, passing exits and identical installed native
   package profiles. Record this setup cost separately.
3. Set the experimental repository variable
   `SMARTCI_TEXTUAL_CANDIDATE_ENROLLMENT_RUN` to that verified run. Create
   `codex/runtime-candidate-enrolled` at its exact head without merging. This
   explicit pilot reference is not automatic trusted artifact discovery.
4. Create a PR against that exact base replaying the existing real Markdown
   regression. The candidate job downloads and verifies enrollment provenance,
   builds the candidate twice and checks determinism, then executes native pytest
   on the proposed files. Missing/invalid evidence executes the full command.
   The separate native control always runs all tests. Native failures stay red.
5. Download both jobs' artifacts and GitHub run/jobs metadata. Run
   `examples/textual/compare_candidate.py --artifacts PAIR --enrollment SEED
   --output REPORT`. It checks actual case identities against selected files,
   matches outcomes/skips and lists every native failure omitted by the candidate.

Report trigger-to-job completion, runner-seconds, planning and test duration, and
enrollment cost. Candidate feedback savings are potential, not production
pipeline savings: this workflow still waits for its full control. Preserve failed
comparisons, missing evidence and runner variance; do not cherry-pick retries.

## Verification and remaining work

Focused tests cover observed callers, processes, shared scopes, stale/tampered
maps, unobserved methods, broad/add/delete/test edits, unchanged fallback failures,
missing full controls and missed native failures. Run `make check` and `uv build`.
No AWS deployment or credentials are required. Hosted results must be recorded
after execution; code/tests alone establish neither Textual compatibility nor a
speedup. Promotion requires evidence addressing the unresolved dependency classes,
additional real changes, and a separately reviewed execution policy.
