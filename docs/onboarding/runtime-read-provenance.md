# Source-read provenance before selective execution

The completed Textual comparison found a faster experimental subset, but the
runtime map still records shared source-file opens without their origin. A source
reader can observe a body-only change without executing the changed function.
Discarding those reads merely because coverage probably caused them would weaken
the safety rules. This probe records their origin before making that decision.

The optional `smartci.adapters.runtime_reads` pytest plugin runs alongside scoped
runtime observation. It writes a separate report bound to the exact observation
bytes, Git revision and tracer implementation. Existing observation schemas,
production plans, fallback rules and the agent's authority are unchanged.

For tracked files it records the temporal context, a lifecycle label and at most
24 Python stack frames. Repository frames contain relative paths and line numbers;
external frames contain only fixed library-family labels such as `coverage`,
`importlib` or `other`. No source contents, frame locals, function arguments,
process arguments, arbitrary module names or external paths are persisted. Frames
are inspected without importing repository code or requesting extra fixtures.
Repeated records are deduplicated. The trace is bounded to 5,000 unique records and
8 MiB of encoded event data; record/byte-limit exhaustion or missing hooks becomes
explicit evidence that cannot pass the assessment. Truncated stacks remain marked
as incomplete in the assessment and cannot establish the absence of other callers.

Lifecycle labels distinguish before tests, each test protocol, between protocols,
after all collected protocols and session finish. Background-thread activity gets
an unknown-thread label, never the active main-thread test's ownership. These are
temporal facts, not exclusive dependency ownership. An event count is a count of
unique records, not the number of actual file reads.

Library labels are derived from observed module names and are not authentication
of third-party code. Python audit hooks can be bypassed; stack truncation, native
code, children and shared state remain limitations. A read after tests can still
affect coverage thresholds, snapshots, reports or the process exit code. The probe
does not authorize ignoring any of these effects. See the
[Python audit-hook contract](https://docs.python.org/3.14/library/sys.html#sys.addaudithook)
and [pytest protocol hooks](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_runtest_protocol).

## Bounded GitHub verification

Use an isolated Textual fork PR with unchanged application sources, tests, locked
dependencies, Python version, coverage flags and workers. Run the existing two-arm
full observation workflow, pinning the reviewed tool revision. Append
`--trace-source-reads` only to `runtime_candidate.py --mode observe-scoped`.
The native control receives no instrumentation. There are no API credentials or
model calls; each job retains the existing 20-minute timeout and seven-day
artifact retention.

Download both artifacts and the run/first-attempt job metadata. From the pinned
Smart CI checkout, run:

```sh
uv run --frozen python examples/textual/assess_reads.py \
  --artifacts /path/to/github-artifacts \
  --tracer src/smartci/adapters/runtime_reads.py \
  --path src/textual/widgets/_markdown.py \
  --path src/textual/_xterm_parser.py \
  --output /path/to/new-read-assessment.json
```

The assessment requires identical full native case identities, outcomes, skip
details and package profiles. It rejects wrong revisions, mismatched observation
bytes, wrong tracer hashes, incomplete protocols, trace diagnostics and malformed
events. It preserves late native failures. Every assessment explicitly requires
full execution and denies test omissions or CI savings.

## Completed GitHub probe

[Textual PR #14](https://github.com/SharmaKunal14/textual/pull/14),
[run 45870117385](https://github.com/SharmaKunal14/textual/actions/runs/45870117385),
used tool `2496a169750f178460d2e3fcddbd98b55edd4f95` against source
`5f9ab660537f109fa07ffe8f1d51c4abdf13365d`. Both full jobs passed all 3,467
cases. The assessor reconciled every identity, outcome and skip detail, identical
installed package profiles, exact observation bytes and tracer hash. The trace
contains 2,093 unique records, all 3,467 completed protocols and no limit/hook
diagnostics. No tests were omitted.

Coverage statement inventories match (31,456 statements), but covered-line counts
are 27,110 native versus 27,112 observed. Only `demo/home.py:187` and `:188` differ.
The paired run does not isolate the cause. Matching case outcomes therefore does
not establish identical execution paths or eliminate instrumentation effects.

| Source | Before-test import records | After-test reporting records | During-test records |
| --- | ---: | ---: | ---: |
| `src/textual/widgets/_markdown.py` | 1 | 2 | 0 |
| `src/textual/_xterm_parser.py` | 1 | 2 | 0 |

The shared records for both subjects occurred after all test protocols. Their
captured stacks contain `coverage` and `pytest_cov` frames. The collection reads
contain import frames; Markdown's also records the widget loader and snapshot
test module. These observations support reporting as the origin of the captured
shared reads. Every displayed stack is truncated at the configured bound, so the
report cannot exclude other callers or unobserved behavior.

Native feedback took 346 seconds; full observation plus the probe took 481 seconds
from workflow creation to each job's completion. Combined runner time was 821
seconds. The 135-second difference includes the existing observer, the new probe
and setup/runner variability; it does not isolate the new plugin's overhead.
These are investigation costs, **not selective-CI savings**. The prior three-arm
result remains unchanged and must not be replaced with this passing baseline.

**Decision:** preserve reporting as separate required CI work; do not convert
these source-read records into blanket test dependencies or silently discard
them. Coverage thresholds and reporting exit status still need an execution
contract before any refinement. Unobserved methods, dynamic loading and
shared/background state remain unresolved; production full fallback is unchanged.
No additional agent trial is justified by this result alone.

The [durable evidence record](../benchmarks/textual-read-provenance-2026-11-27.json)
contains exact job links, timings, trace records, source comparison and artifact
hashes. [Hosted safety checks](https://github.com/SharmaKunal14/smart-ci/actions/runs/45869621585)
passed 1,009 tests, formatting, lint, strict typing and package builds.
[Smart CI PR #26](https://github.com/SharmaKunal14/smart-ci/pull/26) contains the
implementation. Both PRs remain unmerged. No model calls or AWS deployment.

For the command above, download the run's `textual-native-1` and
`textual-observe-scoped-1` artifacts, preserving those directory names. Save
`gh api repos/SharmaKunal14/textual/actions/runs/45870117385` as `run.json` and
`gh api 'repos/SharmaKunal14/textual/actions/runs/45870117385/attempts/1/jobs?per_page=100'`
as `jobs.json` alongside them. Use the pinned tool checkout's tracer file. Expected:
matching outcomes, the counts above, `execution_required: full`, and
`ci_savings_demonstrated: false`. Artifact retention is seven days.
