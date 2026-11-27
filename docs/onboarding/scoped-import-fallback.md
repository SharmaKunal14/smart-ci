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
