"""Validate immutable base-map bytes authenticated by a trusted CI transport.

An expected digest is an integrity binding, not authentication by itself. Never
take it from PR-controlled files or from the same unverified archive as the map.
The GitHub fetch adapter obtains it only after validating producer provenance.
"""

import hashlib
import re
from pathlib import Path

from smartci.adapters.runners import read_bounded
from smartci.contracts import TestUnit
from smartci.git_changes import git
from smartci.selection import digest

from .collector import node_id, test_id
from .models import TypeScriptConfig, TypeScriptSnapshot
from .workspace import check_environment


def load_base_map(
    root: Path,
    base: str,
    head: str,
    config: TypeScriptConfig,
    path: Path,
    expected_digest: str,
) -> TypeScriptSnapshot:
    if re.fullmatch(r"[a-f0-9]{64}", expected_digest) is None:
        raise ValueError("trusted map digest required")
    if path.is_symlink() or path.resolve(strict=True).is_relative_to(root):
        raise ValueError("map must be outside the application checkout")
    payload = read_bounded(path, limit=32 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise ValueError("map integrity mismatch")
    saved = TypeScriptSnapshot.model_validate_json(payload)
    if (
        saved.digest != digest(saved.model_dump(exclude={"digest"}))
        or saved.repository != config.repository
        or saved.graph.repository != config.repository
        or saved.inventory.repository != config.repository
        or saved.graph.commit != base
        or not saved.graph.complete
        or saved.graph.unsupported
        or not saved.inventory.complete
        or saved.gaps
        or saved.provenance.get("configuration") != digest(config.model_dump())
        or saved.inventory.environment != digest(saved.provenance)
        or len(saved.files) > 100_000
        or len(saved.analyzed) > 100_000
        or len(saved.widened) > 100_000
    ):
        raise ValueError("map binding or completeness mismatch")
    files = git(root, "ls-tree", "-r", "--name-only", "-z", base).decode().split("\0")
    paths = [p for p in files if p]
    for p in paths:
        TestUnit.relative_path(p)
    owners = {p: node_id(p) for p in paths}
    tests = {test_id(p): node_id(p) for p in saved.files}
    if (
        not saved.files
        or saved.files != sorted(set(saved.files))
        or not set(saved.files) <= set(paths)
        or saved.graph.owners != owners
        or set(saved.graph.dependencies) != set(owners.values())
        or saved.graph.tests != tests
        or {t.id: t.path for t in saved.inventory.tests}
        != {test_id(p): p for p in saved.files}
        or any(
            t.runner != "vitest" or t.granularity != "file"
            for t in saved.inventory.tests
        )
        or not set(saved.files) <= set(saved.analyzed)
        or not set(saved.analyzed) <= set(paths)
        or not set(saved.widened) <= set(paths)
    ):
        raise ValueError("map tree or inventory mismatch")
    check_environment(
        root,
        base,
        head,
        config.native_project.lockfile
        if config.native_project
        else "package-lock.json",
    )
    return saved
