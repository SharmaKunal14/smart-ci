"""Acceptance gate for this pinned method: passing native cases and all body lines."""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from compare_observation import junit, read

BODY_LINES = frozenset({694, 695, 696, 697, 698, 699, 705, 706})


def verify(coverage: bytes, outcomes: bytes) -> None:
    cases = junit(outcomes)
    if any(outcome != "passed" for outcome, _ in cases.values()):
        raise ValueError(
            "generated tests must all pass without skips or expected failures"
        )
    if (
        b"<!DOCTYPE" in coverage.upper()
        or b"<!ENTITY" in coverage.upper()
        or b"\0" in coverage
    ):
        raise ValueError("unsafe coverage XML")
    matches = [
        node
        for node in ET.fromstring(coverage).iter("class")
        if node.get("filename") == "widgets/_markdown.py"
    ]
    if len(matches) != 1:
        raise ValueError("target coverage file missing or ambiguous")
    pairs = [
        (int(node.attrib["number"]), int(node.attrib["hits"]))
        for node in matches[0].iter("line")
    ]
    hits = dict(pairs)
    if len(hits) != len(pairs) or any(hits.get(line, 0) <= 0 for line in BODY_LINES):
        raise ValueError("every recorded target-body line must execute")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    args = parser.parse_args()
    verify(read(args.coverage), read(args.junit))
    print(
        "Generated cases passed and all eight target-body lines executed. Semantic review still required.",
        flush=True,
    )


if __name__ == "__main__":
    main()
