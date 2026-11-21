# date-fns: real repository evaluation

This pilot extends the existing TypeScript 5 / Vitest 3 adapter to **TypeScript
7.0.x, Vitest 5.0.x, Node 26 and a pnpm workspace**. It preserves the repository's
Vitest configuration, default worker count, isolation and filesystem cache. It
does not claim support for every TypeScript repository or the entire date-fns CI
matrix.

Fork: https://github.com/SharmaKunal14/date-fns

Pinned upstream revision: `a9739fb3e5384a810e90d7376446f6d84ecc5029`.
Native dependencies: unchanged `pnpm-lock.yaml`; pnpm 12.21.0 and Node 26.13.1.

## What is enrolled

The **core/main Node project in UTC**: 253 test files, 3,167 cases, 3,148 passes
and 19 upstream skips on the unmodified baseline. The initial native measurements
were 2.70s on the first run, then 1.16s and 0.97s with the native cache retained.
This is already a very fast suite. A large source repository is not necessarily
a slow test workload.

Three-round local paired measurements (wall-clock medians):

| Real scenario | Native full | Smart CI including planning | Smart CI files | Observed failures missed |
| --- | ---: | ---: | ---: | ---: |
| Chinese month-parsing regression replay | 1.05s | 12.02s | 4 / 253 | 0 of 6 |
| Upstream fix reapplied | 1.04s | 12.48s | 4 / 253 | No native failures to detect |
| Actual package-export/build change | 1.00s | 4.14s | 253 / 253, fallback | No native failures to detect |

The subset contains 19 cases versus 3,167 in the full suite. Vitest's existing
`related` command ran three files/six cases for the locale change, detected all
six failures and took about 1.19s. Smart CI additionally retained one test file
whose unresolved external import conservatively broadens its dependencies.
It was not dropped to improve the benchmark.

**There is no demonstrated speedup here.** Reconstructing both graphs and the
private base dependency environment dominates this workload. Every scenario's
three decision digests matched and no observed failures were omitted, but one
historical defect is weak evidence for universal regression-detection recall.
Raw measurements and case IDs are in
[`docs/benchmarks/date-fns-2026-11-21.json`](../benchmarks/date-fns-2026-11-21.json).
Treat the result as an adapter/correctness evaluation and an unsuccessful
performance hypothesis, not a production efficiency win.

The 19 skips are 18 DST assertions that upstream disables in UTC and one
browser-only iframe assertion. Each reviewed exception is bound to its test
file's SHA-256, exact case identity and the configured UTC profile. Counts remain
visible. Unknown skips, changed identities or stale source reviews invalidate
reconciliation; observed failures remain failures even when a retry passes.
These reviews are explicit onboarding policy, not automatically inferred proof.

The unchanged native `pkgs/core/scripts/test/tz.sh` also passes its 15 executions
across named timezones locally. It remains an independent full check in the
evaluation workflow. Browser tests, the separate Temporal project, other package
test projects, the multi-Node-version matrix and the all-timezone matrix are **not
enrolled in selective execution**. Their normal checks must remain authoritative
before production adoption. This pilot does not replace them.

## How discovery and execution work

1. Vitest resolves the existing named project and lists its files twice. The two
   inventories must agree. The adapter never supplies a replacement test config.
2. TypeScript 7's installed compiler API resolves imports, re-exports, project
   references, extended tsconfigs and workspace package exports. The compiler's
   canonical paths are mapped back to exact Git filenames. Test files are graph
   nodes; no handwritten list maps production files to tests.
3. Smart CI reconstructs the merge base in a temporary checkout. All workspace
   manifests and the lockfile must match before reusing dependency evidence.
   pnpm installs into that checkout **offline, frozen and without lifecycle
   scripts**, using a separately populated package store and metadata cache.
   Supply-chain checks remain enabled. Sharing head's entire `node_modules`
   would risk resolving old imports to new workspace source, so it is avoided.
4. Reverse reachability through the union of base and head graphs selects whole
   test files. Computed imports, filesystem access and unresolved relationships
   conservatively broaden their consumers. Unsupported native plugins/aliases,
   focused tests, missing evidence and risky configuration changes force full
   execution of the enrolled project.
5. Native Vitest executes the files using upstream worker/isolation settings.
   Results must reconcile with the requested inventory. A partial/inconsistent
   subset triggers an independent full run; failures are never erased.

The installed TypeScript API used here is explicitly unstable. The adapter is
version-bounded and needs revalidation when that API changes. The native project
uses `isolate: false`; selection assumes its tests do not require omitted tests
to initialize shared state. The audit records that assumption as a warning. A
finite regression comparison cannot prove this property for every future change.

## Reproduce the setup

From the Smart CI root, use a disposable clone. These commands download public
source and test dependencies; they provision no cloud resources.

```sh
uv sync --frozen
mkdir -p demo-output/date-fns
git clone https://github.com/SharmaKunal14/date-fns.git demo-output/date-fns/repository
git -C demo-output/date-fns/repository checkout --detach a9739fb3e5384a810e90d7376446f6d84ecc5029
npm install --prefix demo-output/date-fns/runtime node@26.13.1 pnpm@12.21.0

export SMARTCI_NODE="$PWD/demo-output/date-fns/runtime/node_modules/node/bin/node"
export SMARTCI_PNPM="$PWD/demo-output/date-fns/runtime/node_modules/pnpm/bin/pnpm.mjs"
export SMARTCI_STORE="${TMPDIR:-/tmp}/smartci-datefns-pnpm-store"
export SMARTCI_CACHE="${TMPDIR:-/tmp}/smartci-datefns-pnpm-cache"
export PATH="$(dirname "$SMARTCI_NODE"):$PATH"

"$SMARTCI_NODE" "$SMARTCI_PNPM" --dir demo-output/date-fns/repository \
  install --frozen-lockfile --store-dir "$SMARTCI_STORE" --cache-dir "$SMARTCI_CACHE"
```

If that clone already exists, inspect its status and use it rather than deleting
it. Choose a new output directory for each invocation: the CLI refuses to
overwrite previous evidence.

```sh
uv run --frozen smartci typescript scan \
  --repo demo-output/date-fns/repository \
  --config examples/date-fns/typescript.json \
  --node "$SMARTCI_NODE" --output demo-output/date-fns/my-scan --run-full
```

Expected: 253 files, no graph gaps, full execution, 3,167 cases and 19 reviewed
skips. On macOS, append `--offline` to block outbound network for discovery and
tests. That flag requires `sandbox-exec`; the pnpm base installation itself uses
`--offline` on every platform. Offline mode is not a general code sandbox.

## Reproduce an actual historical regression and fix

The upstream fix is
[`b9c5865edb7610c59e6b3694ed1e1691f4807688`](https://github.com/date-fns/date-fns/commit/b9c5865edb7610c59e6b3694ed1e1691f4807688).
Replay only its three production-file changes, retaining **all current upstream
tests**. This is a replay on the pinned modern environment, not a claim that the
entire old commit and its old dependencies were executed.

```sh
git -C demo-output/date-fns/repository show --format= \
  b9c5865edb7610c59e6b3694ed1e1691f4807688 -- \
  pkgs/core/src/locale/zh-CN/_lib/match/index.ts \
  pkgs/core/src/locale/zh-HK/_lib/match/index.ts \
  pkgs/core/src/locale/zh-TW/_lib/match/index.ts > demo-output/date-fns/chinese-fix.patch
git -C demo-output/date-fns/repository switch -c codex/local-chinese-regression
git -C demo-output/date-fns/repository apply --reverse "$PWD/demo-output/date-fns/chinese-fix.patch"
git -C demo-output/date-fns/repository add pkgs/core/src/locale
git -C demo-output/date-fns/repository commit -m 'Replay historical Chinese month parsing regression'

uv run --frozen python scripts/benchmark_date_fns.py \
  --repo demo-output/date-fns/repository \
  --config examples/date-fns/typescript.json \
  --base a9739fb3e5384a810e90d7376446f6d84ecc5029 --expect failed \
  --node "$SMARTCI_NODE" --pnpm "$SMARTCI_PNPM" \
  --dependency-store "$SMARTCI_STORE" --dependency-cache "$SMARTCI_CACHE" \
  --output demo-output/date-fns/my-regression --rounds 3
```

The benchmark succeeds only if the native full run observes the expected
failure, Smart CI also fails, and Smart CI omits none of the observed failing
case IDs. It runs three rotated-order rounds against native full execution and
Vitest's built-in `related` command. Full CLI startup, both map rebuilds and
execution are included in Smart CI time. Installation and runner provisioning
are excluded from all paired timings. All caches remain enabled.

Save the full regression commit ID with `git rev-parse HEAD`. Apply the same
patch forward, commit, and rerun with that ID as `--base`, `--expect passed` and
a fresh output directory. This tests the actual fix without altering tests.

For the broad-change control, check out the pinned upstream revision again and
use its full parent ID as `--base`. Its real package-export/build-script changes
must run the full enrolled suite. An empty or incomplete native `related` result
is reported as such; it is not treated as a successful safety comparison.

## Verification and integration

```sh
export SMARTCI_TYPESCRIPT_NODE_MODULES="$PWD/demo-output/onrecord/repository/node_modules"
export SMARTCI_TS7_NODE_MODULES="$PWD/demo-output/date-fns/repository/node_modules"
export SMARTCI_TS7_NODE="$SMARTCI_NODE"
make check
uv build
```

The two optional dependency environments enable actual compiler/runner tests;
without them, pytest reports the corresponding integration tests as skipped.
No new Python runtime dependency was added.

`scripts/render_date_fns_ci.py` generates a test-only pull-request workflow from
`examples/date-fns/pull-request.yml.in`, with an immutable published Smart CI
commit. It checks out full Git history, installs the native environment, runs an
independent full control and timezone scripts, then invokes Smart CI. A final
gate preserves failures from every test step, including when Smart CI succeeds.
It uses read-only repository permissions, no persisted checkout credentials, a
15-minute limit and three-day artifact retention. The independent full control
is intentional evaluation overhead; this pilot does not claim CI savings from
running both the full suite and a subset.

AWS deployment: **none**. There is no Lambda, CloudFormation stack, hosted service
or paid model in this implementation. For this suite, any decision to remove the
full evaluation control must first be justified by broader safety evidence and
positive net timing results; fewer selected files alone are insufficient.
