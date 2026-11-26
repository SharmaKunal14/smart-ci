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
8 MiB of encoded event data; truncation or missing hooks becomes explicit evidence
that cannot pass the assessment.

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

Hosted results are pending. This is a targeted dependency investigation, not
another agent trial or evidence of improved selective performance. A result that
attributes reads to reporting narrows one unknown but does not resolve unobserved
methods, dynamic loading or background state. The next execution policy must
preserve any reporting/build work and independently address those remaining gaps.
