"""Join trusted artifact retrieval, missing-map reconstruction and native PR execution.

Retrieval happens in a preceding token-scoped CI step. This process receives no
credentials and never publishes a PR-produced map as a trusted baseline.
"""

import argparse
import json
import subprocess
from pathlib import Path

from smartci.bazel.bundle import canonical, read_bounded
from smartci.bazel.collection import collect, read_config, reusable_bundle
from smartci.bazel.commands import revision_tree, verify_checkout
from smartci.bazel.execution import execute, read_execution_config


def checkout(repo: Path, revision: str) -> None:
    subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            "checkout",
            "--quiet",
            "--detach",
            revision,
        ],
        check=True,
        timeout=30,
    )
    verify_checkout(repo, revision)


def run(
    repo: Path,
    base: str,
    head: str,
    fetched: Path,
    capture_config: Path,
    execution_config: Path,
    output: Path,
    publisher_capture: Path | None = None,
) -> dict[str, object]:
    # Validate exact revisions before they can become Git arguments.
    if not all(
        len(r) == 40 and set(r) <= set("0123456789abcdef") for r in (base, head)
    ):
        raise ValueError("exact commits required")
    verify_checkout(repo, head)
    if output.is_relative_to(repo) or any(
        p.is_relative_to(output) for p in (fetched, capture_config, execution_config)
    ):
        raise ValueError("external output must not contain trusted inputs")
    output.mkdir(mode=0o700, exist_ok=False)
    execution = read_execution_config(execution_config)
    capture = read_config(capture_config)
    if capture.profile != execution.profile:
        raise ValueError("capture and execution profiles differ")
    bundle = None
    digest = None
    lifecycle = {"map": "unavailable", "rebuild": None}
    try:
        receipt = json.loads(read_bounded(fetched / "fetch.json", 16384))
        if receipt["status"] != "ready" or not isinstance(
            receipt["manifest_digest"], str
        ):
            raise ValueError("retrieval did not authenticate a map")
        reusable_bundle(
            fetched / "bundle",
            receipt["manifest_digest"],
            read_config(
                publisher_capture or Path(__file__).with_name("publisher-capture.json")
            ),
            repo,
            revision_tree(repo, base),
        )
        bundle, digest = fetched / "bundle", receipt["manifest_digest"]
        lifecycle["map"] = "retrieved"
    except (OSError, ValueError, TypeError, KeyError):
        print(
            "No retrieved map; rebuilding from the exact PR base before planning.",
            flush=True,
        )
        try:
            checkout(repo, base)
            rebuilt = collect(repo, base, capture, output / "rebuild")
            lifecycle["rebuild"] = rebuilt["status"]
            if rebuilt["status"] == "ready" and isinstance(
                rebuilt["manifest_digest"], str
            ):
                bundle, digest = output / "rebuild/bundle", rebuilt["manifest_digest"]
                lifecycle["map"] = "rebuilt"
        except (OSError, ValueError, subprocess.SubprocessError):
            lifecycle["rebuild"] = "failed"
        finally:
            # A failed restore must stop CI, never run tests on the wrong revision.
            checkout(repo, head)
    (output / "lifecycle.json").write_bytes(canonical(lifecycle))
    return execute(
        repo,
        base,
        head,
        execution,
        output / "execution",
        bundle_path=bundle,
        expected_digest=digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "fetched", "capture-config", "execution-config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--publisher-capture", type=Path)
    args = parser.parse_args()
    report = run(
        args.repo.resolve(),
        args.base,
        args.head,
        args.fetched.resolve(),
        args.capture_config.resolve(),
        args.execution_config.resolve(),
        args.output.resolve(),
        args.publisher_capture.resolve() if args.publisher_capture else None,
    )
    code = report["exit_code"]
    return (
        code
        if isinstance(code, int) and 0 < code <= 255
        else 0
        if report["status"] == "passed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
