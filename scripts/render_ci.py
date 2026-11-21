"""Generate a reviewable workflow replacing exactly one pinned packaging matrix cell."""

import argparse
import hashlib
import re
from pathlib import Path

from pydantic import TypeAdapter

from smartci.ci.models import Repository

ROOT = Path(__file__).resolve().parents[1]


def render(original: str, tool_repository: str, tool_ref: str) -> str:
    expected = "7d25316a78766a11c15a8aea92e6a7e2465370c193ec12668616b955f8efa65f"
    if hashlib.sha256(original.encode()).hexdigest() != expected:
        raise ValueError(
            "enrollment requires the reviewed packaging workflow; review upstream drift"
        )
    TypeAdapter(Repository).validate_python(tool_repository)
    if not re.fullmatch(r"[0-9a-f]{40}", tool_ref):
        raise ValueError("immutable 40-character tool commit required")
    anchors = ["  pull_request:\n", "        exclude:\n", "      - musl\n"]
    if any(original.count(anchor) != 1 for anchor in anchors):
        raise ValueError("upstream workflow changed; review enrollment manually")
    if (
        "smartci-native:" in original
        or 'python_version: "3.14"\n          - os:' in original
    ):
        raise ValueError("workflow already enrolled or unsupported")
    original = original.replace(
        "  pull_request:\n", "  pull_request:\n  workflow_dispatch:\n"
    )
    original = original.replace(
        "        exclude:\n",
        '        exclude:\n          # Executed once by smartci-native below.\n          - os: Ubuntu\n            python_version: "3.14"\n',
    )
    original = original.replace(
        "      - musl\n", "      - musl\n      - smartci-native\n"
    )
    jobs = (ROOT / "examples/onboarding/packaging/shadow-jobs.yml.in").read_text()
    jobs = jobs.replace("TOOL_REPOSITORY", tool_repository).replace(
        "TOOL_COMMIT", tool_ref
    )
    return original.rstrip() + "\n\n" + jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--tool-repository", required=True)
    parser.add_argument("--tool-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve().is_relative_to(
        args.repo.resolve()
    ):
        parser.error("use a fresh output file outside the target repository")
    source = (args.repo / ".github/workflows/test.yml").read_text()
    content = render(source, args.tool_repository, args.tool_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content)
    print(f"Reviewable workflow written to {args.output}; no repository changed.")


if __name__ == "__main__":
    main()
