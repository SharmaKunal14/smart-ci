"""Bound and fingerprint a native cache; the caller authenticates its publisher.

Only build outputs belong here. A matching digest is not publisher authentication:
the expected manifest must arrive through a separately trusted CI artifact.
"""

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 2 * 1024**3
MAX_ENTRIES = 100_000
CACHE_OPTION = "--disk_cache=/native-cache"
CACHED_FULL_OPTIONS = "e70f1e26dce149e3d2f3fca27abbfb726b94c96aac567d6e45ae665e3fa01978"


def validate_profile_options(options: str, cache: Path | None) -> None:
    if bool(cache) != (options == CACHED_FULL_OPTIONS):
        raise ValueError("cache directory and reviewed cached profile must agree")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate cache receipt key")
        result[key] = value
    return result


def cache_arguments(cache: Path | None, repo: Path, output: Path) -> tuple[str, str]:
    if cache is None:
        return "", ""
    if (
        not cache.is_absolute()
        or cache.resolve(strict=True) != cache
        or not cache.is_dir()
        or not re.fullmatch(r"[/._a-zA-Z0-9-]+", str(cache))
        or any(
            cache.is_relative_to(p) or p.is_relative_to(cache) for p in (repo, output)
        )
    ):
        raise ValueError("separate canonical native cache directory required")
    return f" --mount type=bind,source={cache},target=/native-cache", " " + CACHE_OPTION


def fingerprint(directory: Path) -> dict[str, str | int]:
    if (
        not directory.is_absolute()
        or directory.resolve(strict=True) != directory
        or not directory.is_dir()
    ):
        raise ValueError("canonical cache directory required")
    entries = 0
    total = 0
    records: list[tuple[str, int, str]] = []

    def walk(parent_fd: int, relative_parent: str, depth: int) -> None:
        nonlocal entries, total
        if depth > 64:
            raise ValueError("cache nesting exceeds limit")
        with os.scandir(parent_fd) as children:
            for child in children:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ValueError("cache entry limit exceeded")
                before = child.stat(follow_symlinks=False)
                relative = relative_parent + child.name
                if len(relative) > 1024:
                    raise ValueError("cache path exceeds limit")
                if stat.S_ISDIR(before.st_mode):
                    descriptor = os.open(
                        child.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    try:
                        walk(descriptor, relative + "/", depth + 1)
                    finally:
                        os.close(descriptor)
                    continue
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise ValueError("cache contains a link or special file")
                total += before.st_size
                if total > MAX_BYTES:
                    raise ValueError("native cache exceeds the 2 GiB upload cap")
                digest = hashlib.sha256()
                count = 0
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                with os.fdopen(
                    os.open(child.name, flags, dir_fd=parent_fd), "rb"
                ) as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_mode) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_mode,
                    ):
                        raise ValueError("cache changed while inspecting")
                    while chunk := stream.read(1024 * 1024):
                        count += len(chunk)
                        if count > before.st_size:
                            raise ValueError("cache file grew while inspecting")
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                if count != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                    raise ValueError("cache changed while inspecting")
                records.append((relative, count, digest.hexdigest()))

    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(descriptor, "", 0)
    finally:
        os.close(descriptor)
    if not records:
        raise ValueError("empty cache is not a warm seed")
    raw = json.dumps(sorted(records), separators=(",", ":")).encode()
    return {
        "schema_version": "1",
        "tree_digest": hashlib.sha256(raw).hexdigest(),
        "bytes": total,
        "files": len(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.directory.resolve()):
        parser.error("receipt must be outside the cache")
    actual = fingerprint(args.directory)
    if args.expected is not None:
        if args.expected.stat().st_size > 4096:
            raise ValueError("cache receipt exceeds limit")
        expected = json.loads(
            args.expected.read_bytes(), object_pairs_hook=unique_object
        )
        if (
            not isinstance(expected, dict)
            or any(type(expected.get(k)) is not type(v) for k, v in actual.items())
            or expected != actual
        ):
            raise ValueError("native cache differs from the approved seed")
    with args.output.open("x") as stream:
        stream.write(json.dumps(actual, sort_keys=True) + "\n")
    print(json.dumps(actual), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
