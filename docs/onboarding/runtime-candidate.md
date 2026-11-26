# Runtime candidate evaluation

This experiment asks whether function-entry observations can identify a useful
candidate for Textual's real Markdown regression. It does **not** authorize
production omissions. The deterministic production selector is unchanged; the
independent native full job remains required. The bounded model investigation is
complete and further calls are disabled. No AWS resources were created.

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

Approved live scope: one investigation, at most four calls, at most 5,000 input
and 1,000 output tokens per call, regular OpenAI API with public Textual source
only. Reuse the existing ledger without resetting its three reservations. At its
recorded conservative rates, at most US$0.36 additional reservation fits within
the original US$5 campaign ceiling. Pricing was reverified before admission.
The user approved this one bounded investigation on 27 November 2026. Activation
followed verified enrollment and hosted code checks. The ledger retained
its previous reservations and was capped at seven total calls/two investigations
and US$0.63 total reservations, permitting at most four new calls/US$0.36. Model
credentials must exist only in the investigation step and never in test execution.
The existing key is in Smart CI's repository, not the Textual fork; run the three
measurement arms in one Smart CI evaluation workflow against the same pinned real
Textual PR. Report that workflow's full trigger-to-job times and distinguish them
from automatic Textual-PR trigger latency, which this arrangement does not measure.

The implementation builds an explicitly incomplete base graph from positive
runtime observations and an empty head-runtime graph. It hashes exact Git source
objects for the read-only broker; it does not claim old observations describe new
execution. The model can inspect sources, compare change scope and propose
registered positive facts. Applying an accepted edge independently repeats source
verification, then adds any tests whose recorded dependency paths reach that edge
and the changed source. No observed caller can be removed. Missing/unfinished
agent evidence requires full experimental execution as well as the full control.

Enrollment is now verified on [Textual PR #12](https://github.com/SharmaKunal14/textual/pull/12),
[run 45862622090](https://github.com/SharmaKunal14/textual/actions/runs/45862622090):
both paths passed 3,467 cases with identical identities, outcomes and skip details.
Native feedback was 366 seconds; observed feedback 507 seconds. Combined runner
time was 867 seconds. These are one-time enrollment costs, not selection savings.
[Textual PR #13](https://github.com/SharmaKunal14/textual/pull/13) contains the exact
historical Markdown regression with unchanged tests. Its completed comparison is
recorded below; enrollment success is not substituted for that result.

## Completed three-arm result, 27 November 2026

[GitHub run 45865417885](https://github.com/SharmaKunal14/smart-ci/actions/runs/45865417885)
tested source head `62e3ddf22ab3876d39b279358f6f7f485db5f557` using tool revision
`0fc00dcbf277a6bd1395ed182a606933d141447f`. All three jobs are red because they
preserve the intentional `test_markdown_stream_switch_theme` regression. The
comparison verifier passed: every selected case identity, outcome and skip detail
matched the full control, and neither subset omitted any native failure.

| Arm | Cases | Workflow trigger to job completion | Runner time | Test subprocess |
| --- | ---: | ---: | ---: | ---: |
| Native full suite | 3,467 | 413 s | 411 s | 349.81 s |
| Deterministic candidate | 451 | 199 s | 197 s | 142.59 s |
| Same candidate plus live agent | 451 | 204 s | 202 s | 126.44 s |

Both candidates selected `tests/snapshot_tests/test_snapshots.py` and
`tests/test_pipe.py` automatically. The deterministic path returned results 214
seconds (51.8%) sooner than full execution on this one regression. Its planning
took 1.17 seconds using the enrolled map. The full validation workflow took 414
seconds because the authoritative full control remained required; these are
experimental feedback savings, not demonstrated production pipeline savings.

The live model made four calls: two inspections, one proposal and finish. It
verified `tests/test_pipe.py` -> `tests/deadlock.py` as a process-script dependency.
That edge was absent from this experiment's incomplete head graph, but the process
caller was already mandatory in the deterministic candidate. It added **zero test
files**, recovered **zero additional failures**, and finished **five seconds later**
than the non-agent arm. There is no measured incremental agent benefit here.

Agent preparation/investigation took 34.08 seconds: 4.11 seconds preparing source
evidence and 29.97 seconds for provider/tool work. Do not interpret the five-second
overall difference as the entire model overhead: its identical test list happened
to execute about 16 seconds faster, and setup time varied too. This single run
cannot establish an average speedup or characterize model quality generally. The
addition-only design does not test using an LLM to remove deterministic targets.

Reported usage was 9,937 input and 230 output tokens, approximately US$0.088696 at
the reverified standard uncached generation rates. This is an estimate, not an
invoice. US$0.36 in new reservations is retained (US$0.63 across the two
investigations in the same campaign). The ledger and one-shot workflow gate are
disabled. No reservations were reset, no extra trials were run, and no merge or
AWS deployment occurred. The three measurement jobs used 810 runner-seconds,
separate from the enrollment's 867 runner-seconds and code safety checks.

Known limitations remain: `MarkdownTableContent._update_rows` was unobserved in
enrollment; source reads, shared/background state and broader dynamic dependencies
are unresolved. The production selector still requires full execution. Catching
one known regression does not prove that future omissions are safe.

The [durable evidence record](../benchmarks/textual-runtime-threeway-2026-11-27.json)
contains exact job links, source/tool revisions, outcome hashes, timing boundaries,
model accounting and the incremental comparison. Hosted safety run
[45864871832](https://github.com/SharmaKunal14/smart-ci/actions/runs/45864871832)
passed all 989 tests, formatting, lint, strict types and wheel/source builds.

To verify, download `textual-native-1`, `textual-candidate-1` and `textual-agent-1`
from the measurement run, and both artifacts from enrollment run `45862622090`.
Retain each artifact in its named directory. Save GitHub's run and first-attempt
jobs JSON as `run.json`/`jobs.json` in each run directory, and Textual PR #13's API
response as `subject-pr.json` beside the measurement artifacts. Then run:

```sh
uv run python examples/textual/compare_threeway.py \
  --artifacts /path/to/measurement --enrollment /path/to/enrollment \
  --output /path/to/new-comparison.json
```

An exit code of zero means the recorded comparison reconciles; it does not change
the intentionally failing tests or approve production omissions. Application
tests receive no model credentials. This is a reviewed
public pilot, not a general privileged workflow for arbitrary untrusted PRs.

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
