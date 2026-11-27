"""Bounded same-VM benchmark accounting; never authorize test omissions."""

import argparse
import hashlib
import json
import os
import stat
import time
from datetime import UTC, datetime
from pathlib import Path

ORDERS = {
    "codex/action-matched-full-1": "full",
    "codex/action-matched-smart-2": "smart",
    "codex/action-matched-smart-3": "smart",
    "codex/action-matched-full-4": "full",
}
ARMS = {"full", "smart"}
OUTCOMES = {"success", "failure", "cancelled", "skipped"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evidence key")
        result[key] = value
    return result


def read(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("regular evidence file required")
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("oversized evidence")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise TypeError("object evidence required")
    return value


def write(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


def stamp() -> dict:
    return {
        "monotonic_ns": time.monotonic_ns(),
        "utc": datetime.now(UTC).isoformat(),
        "boot_hash": hashlib.sha256(
            Path("/proc/sys/kernel/random/boot_id").read_bytes()
        ).hexdigest(),
    }


def initialize(temp: Path, branch: str) -> str:
    if branch not in ORDERS or temp.resolve(strict=True) != temp:
        raise ValueError("canonical runner temp and declared PR required")
    root = temp / "matched-evidence"
    root.mkdir()
    first = ORDERS[branch]
    write(root / "context.json", {"branch": branch, "first": first, **stamp()})
    return first


def begin(temp: Path, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    root = temp / "matched-evidence"
    context = read(root / "context.json")
    other = next(iter(ARMS - {arm}))
    if arm != context["first"] and not (root / other / "end.json").is_file():
        raise ValueError("first arm must finish before the second starts")
    cache = temp / "native-cache"
    if cache.exists() or cache.is_symlink():
        raise ValueError("active cache must be absent before independent restore")
    (root / arm).mkdir()
    write(root / arm / "start.json", stamp())
    cache.mkdir()


def finish(temp: Path, arm: str, outcome: str) -> None:
    if arm not in ARMS or outcome not in OUTCOMES:
        raise ValueError("unknown arm or outcome")
    root = temp / "matched-evidence"
    start = read(root / arm / "start.json")
    cache, used = temp / "native-cache", temp / f"native-used-{arm}"
    if cache.is_symlink() or not cache.is_dir() or used.exists():
        raise ValueError("regular isolated active cache required")
    # Rename, not reuse or upload. The next arm restores into a new empty path.
    cache.rename(used)
    end = stamp()
    if end["boot_hash"] != start["boot_hash"]:
        raise ValueError("runner identity changed")
    write(root / arm / "end.json", {"outcome": outcome, **end})


def verify(temp: Path) -> int:
    root = temp / "matched-evidence"
    context = read(root / "context.json")
    result: dict = {"schema_version": "1", "valid_matched_pair": False}
    try:
        expected = read(temp / "native-cache-receipt/cache.json")
        intervals = {}
        for arm in sorted(ARMS):
            start = read(root / arm / "start.json")
            end = read(root / arm / "end.json")
            receipt = read(root / arm / "cache-verified.json")
            preparation = read(root / arm / "native-preparation.json")
            if (
                receipt != expected
                or preparation
                != {"page_cache_reset": True, "no_active_containers": True}
                or start["boot_hash"] != context["boot_hash"]
                or end["boot_hash"] != context["boot_hash"]
                or type(start["monotonic_ns"]) is not int
                or type(end["monotonic_ns"]) is not int
                or end["monotonic_ns"] <= start["monotonic_ns"]
                or end["outcome"] not in OUTCOMES
            ):
                raise ValueError("unmatched arm evidence")
            intervals[arm] = {
                "start": start,
                "end": end,
                "seconds": (end["monotonic_ns"] - start["monotonic_ns"]) / 1e9,
            }
        first = context["first"]
        second = next(iter(ARMS - {first}))
        if (
            intervals[first]["end"]["monotonic_ns"]
            >= intervals[second]["start"]["monotonic_ns"]
        ):
            raise ValueError("arms overlapped or ran in the wrong order")
        result.update(
            valid_matched_pair=True,
            first=first,
            arms=intervals,
            seconds_saved=intervals["full"]["seconds"] - intervals["smart"]["seconds"],
        )
        success = all(v["end"]["outcome"] == "success" for v in intervals.values())
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        result["error"] = "MISSING_OR_UNMATCHED_EVIDENCE"
        success = False
    write(root / "comparison.json", result)
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["init", "begin", "finish", "verify"])
    parser.add_argument("--arm", choices=sorted(ARMS))
    parser.add_argument("--outcome", choices=sorted(OUTCOMES))
    args = parser.parse_args()
    temp = Path(os.environ["RUNNER_TEMP"])
    if temp.resolve(strict=True) != temp or not temp.is_dir():
        parser.error("canonical runner temp required")
    if args.operation == "init":
        first = initialize(temp, os.environ["GITHUB_HEAD_REF"])
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("first=" + first + "\n")
    elif args.operation == "verify":
        return verify(temp)
    elif args.arm is None:
        parser.error("arm required")
    elif args.operation == "begin":
        begin(temp, args.arm)
    elif args.outcome is None:
        parser.error("outcome required")
    else:
        finish(temp, args.arm, args.outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
