# Scoped expansion for finite Python import targets

This is a deliberately limited implementation of scoped fallback. The collector
can now bound one previously unresolved dependency: `importlib.import_module`
whose argument selects from an inline immutable tuple of known local modules.
For example:

```python
from importlib import import_module as load


def choose(index):
    return load(("app.alpha", "app.beta")[index])
```

Smart CI does not predict `index`. It includes dependencies on **both** modules
and their package initializers. Changes to either module select tests of the
loader and every transitive consumer. Tests outside that affected closure can
be omitted only when all the existing repository, environment, inventory and
dependency checks pass. This is conservative widening of supported dependency
evidence, not a general sandbox or a claim that Python analysis proves isolation.

## Supported boundary and retained fallback

The grammar requires 1–32 literal absolute local module names, each at most 512
characters, and a name or integer index. The loader must be a single top-level
stdlib import binding with no shadowing, reassignment or escaped references.
Variable/mutable tables, computed names, unknown/external targets, relative
imports, kwargs and arbitrary loaders stay unresolved. The tuple bounds the
import's possible target; it does not clear unknown behavior elsewhere.

Every possible target is recorded as `bounded_local` import provenance and
`bounded_import` edges. Audit warnings identify the candidate set and revision.
Selection uses the existing union of base and head dependency graphs, so removed
or renamed relationships remain relevant. Mandatory, new and changed tests and
risk-path rules are unchanged. No new user-authored exemption or scope allowlist
is accepted. Implementation digests invalidate older incompatible maps.

Unknown subprocess effects, `exec`, search-path mutations, unreviewed plugins,
invalid evidence or an unbounded loader in **either revision** still require the
independent full-suite command. Directories and absent historical coverage never
establish containment. Full execution still cannot validate unexercised behavior.

## Textual compatibility conclusion before rerunning

None of the remaining 13 Textual gaps meets this supported boundary. The
[existing cause analysis](textual-planning-efficiency.md) identifies runtime
script paths and code, mutable widget dispatch, computed driver/grammar names,
a shell child, unresolved script/diagnostic imports and unreviewed pytest plugins.
Some relationships may become resolvable with further contracts; their complete
effects are not currently bounded. The global plugin gap alone prevents claiming
a safe subset. No Textual code, test or dependency is altered to fit this grammar.

The real GitHub rerun uses the same PR #17/#18 application/test/lockfile trees and
native commands, with only the shared Smart CI commit pin updated. Expected
result: full fallback remains. Record actual end-to-end results even if negative;
unit fixtures demonstrate behavior, not real repository savings.

## Verified GitHub results — 27 November 2026

**No Textual selection benefit or end-to-end time saving was demonstrated.**
The two real PR comparisons used tool commit
`6d72bb8a049aaa7fde8e51fc12951a31ae020d0b`, shared base
`a1fcda61bfce39f2f503ca7042c115b59b485e0f`, and the existing unchanged native
commands. All source, test, dependency-lock and native inventory identities were
verified. Both strict artifact comparisons passed.

| Real PR / GitHub run | Native trigger → result | Smart CI trigger → result | Native / Smart job duration | Difference |
| --- | ---: | ---: | ---: | ---: |
| [#17 historical regression](https://github.com/SharmaKunal14/textual/actions/runs/45944242876) | 360 s | 440 s | 358 / 438 s | **80 s slower** |
| [#18 uncovered-change control](https://github.com/SharmaKunal14/textual/actions/runs/45944241674) | 324 s | 372 s | 322 / 369 s | **48 s slower** |

Both Smart CI plans selected all **251/251 files**. Each native execution reported
**3,467 case outcomes, including seven native skips**, with zero Smart CI
omissions and `INCOMPLETE_EVIDENCE`. PR #17's only failure
was `tests.snapshot_tests.test_snapshots::test_markdown_stream_switch_theme` in
both arms: 3,459 passed, seven skipped, one failed, and no missed full-control
failure. PR #18 had 3,460 passed and seven skipped in both arms, so there were no
observed failures against which to measure recall. Its green result does not
validate the changed unexercised method.

Planning took **28.48 s** on #17 and **18.32 s** on #18. Native collection and
its repeat consumed 18.45 / 11.91 s respectively; dependency analysis consumed
4.29 / 2.79 s. Native-versus-Smart test execution itself was 314.55 / 351.30 s
on #17 and 285.23 / 299.51 s on #18. Consequently the entire 80/48-second loss
cannot be attributed to planning alone: setup and full-test durations also
differed. One pair per scenario does not isolate runner variation or establish
an average slowdown. There is nonetheless no omitted test work to credit as a
selection benefit.

The source, import, dependency-edge and native-case digests match the preceding
run for each scenario; the same 13 gaps and six plugins remain. There were no
bounded-import audit entries. The new grammar therefore did not help this
Textual configuration. Sibling-script and optional-diagnostic imports need
supported resolution contexts; lazy dispatch needs a verified target contract;
runtime code/path loaders, subprocess effects and global plugin behavior remain
unbounded by the available evidence. This does not prove they can never be
bounded, but it provides no justification for safe omissions now.

The complete validation workflows took 440 and 372 seconds; their four jobs
consumed 1,487 runner-seconds in total. Trigger timing starts at GitHub workflow
creation and includes queue/setup/planning/tests/upload, but excludes earlier
event-delivery latency and the separate tool safety workflow. Optional coverage
reporting remained deferred and native coverage options were unchanged. Results,
revision/environment bindings and artifact hashes are preserved in the
[evidence record](../benchmarks/textual-scoped-imports-2026-11-27.json).

[Smart CI PR #30](https://github.com/SharmaKunal14/smart-ci/pull/30) remains an
unmerged draft. Its benchmarked commit passed
[1,099 hosted tests, formatting, linting, typing and package builds](https://github.com/SharmaKunal14/smart-ci/actions/runs/45943773486).
All model campaign switches remain disabled; this iteration made zero model
calls and no AWS changes. Repeating these same Textual comparisons without a
new, justified dependency boundary would not establish product value.

## Verification

Run `uv sync --frozen`, `make check`, and `uv build`. Focused checks are
`uv run --frozen pytest tests/test_finite_imports.py`. They cover both import
spellings, all candidate targets, transitive consumers, unrelated omissions,
base/head removal and rename, mandatory/new/changed tests, deterministic replay,
binding escapes, unknown targets and retained global fallback. Native pytest
checks a passing baseline, then compares the selected tests' failures against
the full suite after a controlled defect; that is a correctness fixture only.

For hosted evidence, inspect the linked workflow runs and download both
`textual-native-1` and `textual-smart-1` artifacts. Check `selection.json`,
`head-compatibility.json`, `execution.json` and `junit.xml`, then reconcile them
with `examples/textual/compare_coverage_pair.py` and saved run/job/PR metadata.
Use trigger-to-result and job duration including setup, discovery, validation,
tests and artifact upload. No merge, deployment, service setup or model key is
required. The intended customer Action remains separate delivery work.
