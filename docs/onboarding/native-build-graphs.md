# Comparing native build graphs with source and runtime analysis

The active product goal remains unmet. A useful selector must save end-to-end
time while retaining the tested profile's correctness, not merely identify fewer
test files. All performance observations below come from GitHub artifacts.

| Approach | Observed result or current state | Engineering consequence |
|---|---|---|
| Compiler/import graph with cached base evidence | [date-fns PR #7](https://github.com/SharmaKunal14/date-fns/pull/7) narrowed execution, but setup, fetching and planning exceeded saved test time. | Fast native suites leave little overhead budget. Precomputation alone does not establish net savings. |
| Conservative Python import graph | [Textual PR #5](https://github.com/SharmaKunal14/textual/pull/5) retained full fallback after resolving some static gaps. | Computed loaders and resources require explicit supported semantics; clearing warnings is not sufficient. |
| Runtime observation | [Textual PR #6](https://github.com/SharmaKunal14/textual/pull/6): 387s native versus 755s instrumented; same 3,467 outcomes. Observed examples/resources outside the configured roots. | Useful onboarding evidence, expensive in the PR path, and absence of observations cannot justify omissions. |
| Native build graph | New bounded Abseil baseline and graph parser; selection and speedup unverified. | Build tools can provide language-independent declared relationships, but native caching, configuration, non-test builds and undeclared inputs must be accounted for. |

The existing [Bazel query](https://bazel.build/query/language) graph includes all
possible `select` branches. This is conservative with respect to declared build
dependencies, not proof of every runtime dependency. The parser keeps rule
inputs, generated-file generators, external tool dependencies and non-test rules.
It rejects malformed XML, DTDs/entities, duplicate nodes, dangling edges, unknown
target forms and excessive graph/witness sizes. Unknown changed files raise an
error instead of producing an empty affected set. Witness ordering is stable for
fixed inputs. It does not change the current selector or grant skip authority.

## Abseil baseline

- Upstream pin: `82530019412ff77ff99d39ba0ad12e5ea6b89ea4`.
- Fork: [SharmaKunal14/abseil-cpp](https://github.com/SharmaKunal14/abseil-cpp).
- Isolated default branch: `codex/smartci-native-base`; upstream `master` is preserved.
- Baseline: [PR #1](https://github.com/SharmaKunal14/abseil-cpp/pull/1).
- Command: the existing `ci/linux_gcc-latest_libstdcxx_bazel.sh` with `STD=c++17`,
  `COMPILATION_MODE=fastbuild` and `EXCEPTIONS_MODE=-fno-exceptions`.
- Native pinned public container and toolchains retained; anonymous manifest
  inspection found 6,071,717,950 compressed layer bytes. That is an image size,
  not a benchmark measurement. No credentials or private remote cache are used.
- The wrapper only adds a unique Docker container name and a native Build Event
  Protocol output path through upstream hooks. It does not disable test-result
  caching, change test tags, change worker settings or alter application/tests.
- One Ubuntu 24.04 job, 25-minute job limit, 20-minute native process limit,
  read-only permissions and seven-day artifacts. Timeout cleanup targets only
  the uniquely named container created by that invocation.

The wrapper counts native **Bazel test targets**, not internal C++ cases. Native
failures and timeouts remain failing checks. Missing, incomplete or contradictory
event evidence also fails the check. The initial run is not a Smart CI comparison
and cannot establish a benefit. Its GitHub state must be inspected before reporting
completion. Future comparisons must retain build-only checks as well as tests.

## Remaining delivery work

After the native profile succeeds, collect actual query output in the same
toolchain, reconcile it with native target events, bind build definitions and
environment identity, and implement automatic PR execution. Configuration,
dependency-definition, unsupported file and incomplete-evidence changes must
retain full fallback. Do not assume a parsed XML graph is a complete native test
inventory. Verify deleted/renamed files and dependency changes against both
revisions, preserving removed edges.

Compare eligible historical source changes against the independent full native
command on real PRs. Retain ordinary native build/test caches; Bazel itself may
already avoid unchanged work, so this approach may provide little additional
benefit on warm runs. Report any such negative result. A cold-only advantage
must be labeled as such and must not be generalized to cached enterprise CI.

Agentic investigation remains a separate active-goal gate. No live model or
agent benefit is claimed by this baseline or parser. No AWS deployment or merge
is involved.
