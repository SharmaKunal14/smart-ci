# Registered investigation tools and process evidence

Textual's `tests/test_pipe.py` starts `tests/deadlock.py`, which imports the
application. The import-only investigation tool cannot establish the first edge.
The new tool recognizes a bounded form of that relationship from source, without
executing the command. It is reusable Python analysis; Textual paths appear only
in the evaluation harness.

## Implemented behavior

The broker advertises its registered adapters and their evidence relations to the
investigator. An `inspect` action may name one of those adapters. Existing actions
without an adapter continue using the original import verifier. Unknown adapters
are rejected before any source is read. A proposal must match the exact adapter,
implementation digest, revision, source hash, line and broker-issued observation.

`python-process-script-v1` recognizes straight-line imported aliases of selected
`subprocess` calls, `sys.executable`, and `Path(__file__)`-anchored script arguments.
It handles a narrow argv or shell-pipeline grammar. Runtime path computation,
ambiguous local rebinding, unsupported control flow, shell expansion and quoted
pipe syntax are not inferred. Paths must remain inside the recorded repository
catalog. Source AST size and shell token counts are bounded in addition to the
existing source-byte, action and response budgets. It never invokes a shell,
imports target code, follows filesystem links or executes a test.

These are **structural may-depend facts**, not proof that a script runs or an
exhaustive process model. Monkeypatching, environment, shell startup, symlinks,
working-directory behavior and child side effects remain unresolved. Successful
inspection cannot clear a gap, certify completeness, remove existing edges or
authorize omitting tests. The independent full-suite fallback remains authoritative.

`--provider diagnostic-replay` is an offline rule-driven control: it chooses the
process inspector when a `DYNAMIC_PROCESS` diagnostic identifies a source path,
reads both revisions and proposes matching facts. The optional live provider sees
the same registered capability list, but this increment does not enable it or
measure model effectiveness. The previous campaign remains disabled.

## Verification and reproduction

The dedicated `Verify Textual process evidence` workflow audits the captured inputs
from [Textual PR #11](https://github.com/SharmaKunal14/textual/pull/11) and its
[original GitHub run](https://github.com/SharmaKunal14/textual/actions/runs/45058699772).
The harness pins the artifact SHA-256, base/head commits and source digest catalog.
It compares the import-only tool with diagnostic routing using the new inspector,
repeats the latter, and requires identical complete reports. It also requires
that both graphs change only by the one added relationship, preserving every
old edge, completeness flag, test mapping, policy field and unresolved issue.

This workflow performs **no Textual test execution and no performance benchmark**.
Its uploaded `summary.json`, `control.json` and `candidate.json` distinguish new
versioned edges from existing relationships, preserve the full selection and
record zero model calls. The regular Smart CI safety workflow separately runs
formatting, lint, typing, the full test suite and package builds.

To reproduce the investigation with downloaded source evidence and a checkout
containing both recorded revisions:

```sh
uv run --frozen smartci investigate \
  --inputs /path/to/investigation-input.json \
  --repo /path/to/textual --module-root src \
  --provider diagnostic-replay --enable-process-inspection \
  --output /path/to/process-report.json
```

Inspect `accepted_graph.evidence` for the script edge and its source/adapter
digests; `unresolved` and `final.execution` explain why this still requires all
tests. This command alone does not execute them. Do not interpret the proposed
edges as permission to change the CI execution mode.

No deployment or new dependency is required. The audit uses read-only GitHub
permissions, pinned actions, no API secret, a six-minute job timeout and seven-day
artifact retention. Its artifact dependency can expire; rerunning after expiry
requires authenticating another capture, not silently substituting a different
input. GitHub runner usage is separate from model spending.

## Remaining selection problem

The current full fallback cannot become a useful subset merely by adding edges.
The next investigation must distinguish unavoidable dependency breadth from
overly broad import/module initialization relationships, using mechanically
checkable semantics. Dynamic unknowns still need explicit handling. A finer
representation needs independent regression tests and real GitHub full/subset
comparisons before it can authorize exclusions. No speedup is claimed here.
