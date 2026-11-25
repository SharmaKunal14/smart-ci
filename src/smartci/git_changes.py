"""Bounded, read-only Git analysis. Both rename paths are included."""

import re
import subprocess
import tempfile
from pathlib import Path

from .selection import Changes


class GitError(ValueError):
    pass


def git(repo: Path, *args: str, max_bytes: int = 5 * 1024 * 1024) -> bytes:
    if not 0 < max_bytes <= 16 * 1024 * 1024:
        raise GitError("invalid output bound")
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "-C", str(repo), *args],
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError("git unavailable") from exc
        if result.returncode:
            raise GitError("git operation failed")
        output.seek(0)
        data = output.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise GitError("diff exceeds limit")
        return data


def changes_from_git(repo: Path, base: str, head: str, repository: str) -> Changes:
    # Accept object IDs only: never interpret caller input as Git options/revisions.
    if any(
        re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value) is None
        for value in (base, head)
    ):
        raise GitError("commit IDs required")
    if git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise GitError("shallow history")
    merge = git(repo, "merge-base", "--all", base, head).decode().splitlines()
    if len(merge) != 1:
        raise GitError("ambiguous merge base")
    raw = git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-status",
        "-z",
        "--find-renames",
        merge[0],
        head,
        "--",
    )
    tokens = raw.decode("utf-8", errors="strict").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(tokens) - 1:
        status = tokens[index]
        count = 2 if status.startswith(("R", "C")) else 1
        if not status.startswith(
            ("A", "M", "D", "R", "C", "T")
        ) or index + count >= len(tokens):
            raise GitError("unsupported diff")
        paths.extend(tokens[index + 1 : index + count + 1])
        index += count + 1
    # Submodules and symlinks require analysis that this adapter cannot provide.
    for commit in (merge[0], head):
        tree = git(repo, "ls-tree", "-r", "-z", commit)
        for entry in tree.split(b"\0"):
            if entry.startswith((b"160000 ", b"120000 ")):
                raise GitError("unsupported tree entry")
    return Changes(
        schema_version="1",
        repository=repository,
        base=merge[0],
        head=head,
        paths=sorted(set(paths)),
    )
