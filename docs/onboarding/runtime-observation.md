# Runtime dependency observation prototype

This opt-in pytest plugin records positive runtime evidence. It is not a test
selector, and its report cannot be used as a Smart CI snapshot. Every report
states `complete: false` and `omission_authorized: false`. The deterministic
selector and its full-suite fallback are unchanged.

## What is recorded

- Main-thread calls into tracked repository Python files, including calls after
  imports have been cached. Function entry locations help investigate static
  gaps; they do not prove that a particular statement or every branch executed.
- Audit events for tracked file-open attempts and Python import names. Attempts
  are not proof of successful reads or imports. External paths, file contents,
  environment values and subprocess arguments are not recorded.
- Test-call contexts grouped by test file. Collection, setup and teardown are
  shared across all tests. Other-thread audit activity has a separate shared
  context. This avoids assigning a session fixture only to its first consumer.
- Git revision and tracked blob IDs, observer hash, Python/pytest/plugin versions,
  native case count, exit status, limitations, diagnostics and a canonical digest.
  The digest detects accidental alteration; it is not a signature or proof that
  PR-controlled code told the truth.

Audit hooks are bypassable and do not cover every dependency. The profiler only
covers the current thread; native extensions and child processes are incomplete.
Async tasks may outlive a test call. A clean worktree before and after execution
cannot detect transient modifications restored during a test. These limitations
remain even if all native tests pass. See Python's [audit-hook and profiler
documentation](https://docs.python.org/3.14/library/sys.html) and pytest's
[runtest lifecycle](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_runtest_protocol).

## Bounded use

Install this branch in an existing serial pytest environment, then append:

```sh
python -m pytest tests -p smartci.adapters.runtime_observer \
  --smartci-observation /absolute/path/outside/repository/observation.json
```

Preserve the repository's actual test command, dependency lock, coverage and
environment. Reports must be new files outside the checkout. The plugin rejects
dirty tracked files, non-regular Git entries, oversized metadata and xdist workers.
An existing profiler is preserved and reported as missing observation capability.
Unique observations and filename caching are bounded. Diagnostics do not convert
missing observations into permission to omit tests. Test failures retain native
pytest exit status; instrumentation/setup errors also fail visibly.

`examples/textual/benchmark.py --mode observe` runs the complete native Textual
profile with the observer, with a 900-second test-process limit. Its native mode
remains the independent control. `examples/textual/assess_observation.py` verifies
the report digest and the static-gap source revisions, lists observed consumers,
and compares call-only candidates with candidates including shared activity.
It always reports required execution as full. Neither candidate list is an
executable selection plan.

The investigation of the 14 Textual gaps and hosted verification will be recorded
here after the bounded GitHub comparison. No AWS service or paid model is used.
