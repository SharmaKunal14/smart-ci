"""Compatibility entry point; PR orchestration lives in the reusable CLI engine."""

import argparse
from pathlib import Path

from smartci.bazel.lifecycle import run


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
        args.publisher_capture.resolve()
        if args.publisher_capture
        else Path(__file__).with_name("publisher-capture.json"),
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
