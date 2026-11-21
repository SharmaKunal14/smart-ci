"""Check dependency environments before reconstructing an older revision."""

from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.git_changes import git


def manifests(paths: list[str], lockfile: str) -> list[str]:
    return sorted(
        p
        for p in paths
        if p == lockfile
        or p == "pnpm-workspace.yaml"
        or p.endswith(("/package.json", "/.npmrc"))
        or p == "package.json"
        or p == ".npmrc"
    )


def check_environment(root: Path, base: str, head: str, lockfile: str) -> list[str]:
    def paths_at(commit: str) -> list[str]:
        return (
            git(root, "ls-tree", "-r", "--name-only", "-z", commit)
            .decode()
            .strip("\0")
            .split("\0")
        )

    paths = manifests(paths_at(head), lockfile)
    # Inspect both Git trees: a deleted manifest is just as significant as a new one.
    base_paths = manifests(paths_at(base), lockfile)
    if base_paths != paths:
        raise ValueError("workspace manifest set changed")
    for p in paths:
        if git(root, "show", f"{base}:{p}") != read_bounded(root / p):
            raise ValueError("workspace dependency environment changed")
    return paths
