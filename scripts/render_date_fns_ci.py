"""Render the bounded date-fns evaluation workflow with an immutable tool pin."""

import argparse
import re
from pathlib import Path

from pydantic import TypeAdapter

from smartci.ci.models import Repository

ROOT = Path(__file__).resolve().parents[1]


def render(repository: str, ref: str) -> str:
    TypeAdapter(Repository).validate_python(repository)
    if re.fullmatch(r"[a-f0-9]{40}", ref) is None:
        raise ValueError("immutable 40-character Smart CI commit required")
    return (
        (ROOT / "examples/date-fns/pull-request.yml.in")
        .read_text()
        .replace("TOOL_REPOSITORY", repository)
        .replace("TOOL_COMMIT", ref)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-repository", required=True)
    parser.add_argument("--tool-ref", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    content = render(args.tool_repository, args.tool_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(content)
    print(f"Reviewable evaluation workflow: {args.output}")


if __name__ == "__main__":
    main()
