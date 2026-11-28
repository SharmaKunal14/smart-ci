# Experimental Maven reactor profile

This profile automates PR paths to Maven modules. It does not claim to improve
Maven's dependency algorithm. Unlike a native `clean verify` over the full
reactor, it supplies `--projects` automatically. Maven still performs the builds,
native tests and checks; no Java tests or assertions are rewritten.

Use `SharmaKunal14/smart-ci/maven@<reviewed Action commit>` after checking out the
exact PR head with full history and `persist-credentials: false`, setting up the
repository's own JDK/toolchains and restoring its normal dependency cache. The
Action installs a hash-verified pinned CLI. It needs no model, SaaS account or AWS.
Its config defaults to `.github/smartci-maven.toml`, read from the PR base:

```toml
schema_version = "1"
command = ["./mvnw", "--no-transfer-progress"]
timeout_seconds = 900
input_contract = "unreviewed"
reviewed_native_tree_sha256 = "<64-character reviewed native tree digest>"
```

Preserve the repository's actual full command, profiles and native default goals.
This example is not a replacement command for every Maven repository. The local
equivalent is `smartci maven --repo PATH --base SHA --head SHA --output OUTSIDE_REPO`.
The Action returns native failure status and retains logs and selection evidence.
Installation or metadata failures run the independent base-owned full command.
Invalid event/configuration authority fails the check instead of inventing one.

## Eligibility and limits

`declared-reactor-inputs-v1` is an explicit reviewed contract, not a discovery
result or a universal Maven guarantee. Review native plugins, generated inputs,
resource paths, process/filesystem/network access and tests before enabling it.
Changes outside declared Java source/test roots run the full reactor. Models are
collected fresh with the exact native flags and pinned Maven help plugin; active
profiles and native dependency metadata determine module membership. Java changes
cannot alter Maven dependencies under this profile; POM changes always fall back.
Old and new rename paths, new/deleted/changed tests and transitive consumers are
included. Upstream prerequisites and every POM aggregator retain native checks.

The reviewed native tree digest excludes `.github/` orchestration, which this
contract requires not to be an input to Java/native behavior. Its changes still
force full execution on their PR. Every other base-tree update invalidates the
review, until that new revision is reviewed and its digest updated. This is an
intentional experimental restriction, not a completed automatic enrollment and
refresh product. Do not waive it to make a benchmark pass.

Maven classpaths do not constrain arbitrary filesystem/network access. The Action
does not sandbox Java or prove the declared-input contract. An arbitrary loader,
cross-module file access or undeclared service relationship invalidates eligibility.
Use full mode where that boundary is unknown. The first evaluation runs an
authoritative full control alongside every candidate; observed parity is not a
proof of universal safety. This profile has not yet earned a production recommendation.

## HttpClient input review

The pinned native source is `5b9837710dc84eb49c6d1fb0e70ba3b1174cd5e6`.
The effective reactor contains ten projects. The REST module depends on core;
core has no REST dependency. The expensive test module depends on core, cache,
fluent and WebSocket. Its Docker configurations and certificates are classpath
resources; its Docker processes exercise those declared libraries. REST reflection
examines resource-interface methods within its classpath. No runtime-observation
absence is used to erase dependencies.

Native plugin review includes inherited clean/resources/compiler/Surefire/JAR,
toolchain/enforcer, source checkstyle, API compatibility, remote resources and
the core public-suffix-data download. Root RAT scans all source and is retained;
POM aggregators also remain selected. Failsafe and Docker stay enabled for the
integration module whenever that module is selected. Native JUnit group exclusions
remain unchanged. Review establishes a bounded input-contract assumption for this
pinned profile; it is not a general static proof about Java. No module allowlist
or manual test mapping is supplied to the selector.

The evaluation must keep native cache inputs independent, include CLI installation
and fresh model collection in timings, preserve all attempts and known negative
Abseil results, and distinguish a jointly measured two-arm PR from standalone
developer feedback latency.
