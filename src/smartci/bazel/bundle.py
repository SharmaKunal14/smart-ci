"""Portable native evidence with revision, profile and artifact identity checks.

A digest detects substitution only when the caller obtained it through a trusted
channel. Packing does not authenticate the capture's publisher or prove runtime
hermeticity. A reviewed collector must bind capture inputs to the declared commit.
"""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from smartci.contracts import Digest, Identifier

from .audit import NativeInventory, native_inventory, reconcile_graph
from .events import MAX_BEP_BYTES, summarize_bytes, unique_object
from .graph import MAX_NODES, MAX_XML_BYTES, QueryError, QueryGraph, parse_query_xml
from .planning import MAX_TREE_BYTES, TreeEntry, candidate_plan, parse_tree

Revision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
LIMITS = {
    "query.xml": MAX_XML_BYTES,
    "roots.txt": 4 * 1024 * 1024,
    "native.bep.json": MAX_BEP_BYTES,
    "anchor.tree": MAX_TREE_BYTES,
}
MAX_MANIFEST_BYTES = 16 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Profile(StrictModel):
    schema_version: Literal["1"]
    repository: Identifier
    bazel_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    command_digest: Digest
    options_digest: Digest
    environment_digest: Digest
    query_mode: Literal["unconfigured-deps-all"]
    change_model: Literal["reviewed-declared-cpp-inputs-v1"]


class Manifest(StrictModel):
    schema_version: Literal["1"] = "1"
    collector: Literal["bazel-native-bundle-v1"] = "bazel-native-bundle-v1"
    anchor_commit: Revision
    profile: Profile
    artifacts: dict[str, Digest] = Field(min_length=4, max_length=4)
    capture_config_digest: Digest | None = None

    @model_validator(mode="after")
    def known_members(self) -> Self:
        if set(self.artifacts) != set(LIMITS):
            raise ValueError("unsupported evidence member")
        return self


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_bounded(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise QueryError("regular evidence file required")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise QueryError("evidence exceeds size limit")
    return data


def parse_profile(raw: bytes) -> Profile:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise QueryError("profile exceeds size limit")
    return Profile.model_validate(json.loads(raw, object_pairs_hook=unique_object))


def full_native_inventory(raw: bytes, profile: Profile) -> NativeInventory:
    summary = summarize_bytes(raw)
    patterns = []
    for line in raw.splitlines():
        event = json.loads(line, object_pairs_hook=unique_object)
        if "started" in event:
            start = event["started"]
            options = start.get("optionsDescription")
            workspace = start.get("workspaceDirectory")
            if (
                start.get("buildToolVersion") != profile.bazel_version
                or not isinstance(options, str)
                or sha256(options.encode()) != profile.options_digest
                or not isinstance(workspace, str)
                or not workspace
                or start.get("workingDirectory") != workspace
            ):
                raise QueryError("native capture profile mismatch")
        if "pattern" in event["id"]:
            patterns.append(event["id"]["pattern"])
    if patterns not in [[{"pattern": ["..."]}], [{"pattern": ["//..."]}]]:
        raise QueryError("native reference must use the full root wildcard")
    return native_inventory(summary)


@dataclass(frozen=True)
class Bundle:
    manifest: Manifest
    manifest_digest: str
    anchor: dict[str, TreeEntry]
    graph: QueryGraph
    roots: tuple[str, ...]
    native: NativeInventory

    def plan(
        self,
        base: dict[str, TreeEntry],
        head: dict[str, TreeEntry],
        *,
        must_run: tuple[str, ...] = (),
        execution_mode: Literal["paired", "selective"] = "paired",
    ) -> dict[str, object]:
        report = candidate_plan(
            self.anchor,
            base,
            head,
            self.graph,
            list(self.roots),
            self.native,
            must_run=must_run,
            execution_mode=execution_mode,
        )
        report.pop("digest")
        report.update(
            {
                "schema_version": "smartci.bazel-bundle-plan.v1",
                "repository": self.manifest.profile.repository,
                "bundle_digest": self.manifest_digest,
                "map_revision": self.manifest.anchor_commit,
                "profile": self.manifest.profile.model_dump(),
            }
        )
        report["digest"] = sha256(canonical(report))
        return report


def validate_artifacts(manifest: Manifest, artifacts: dict[str, bytes]) -> Bundle:
    if set(artifacts) != set(LIMITS):
        raise QueryError("missing or unexpected evidence member")
    for name, limit in LIMITS.items():
        if (
            len(artifacts[name]) > limit
            or sha256(artifacts[name]) != manifest.artifacts[name]
        ):
            raise QueryError("evidence identity mismatch")
    anchor = parse_tree(artifacts["anchor.tree"])
    graph = parse_query_xml(artifacts["query.xml"])
    if not graph.source_owners.keys() <= anchor.keys():
        raise QueryError("query sources are absent from the revision tree")
    roots = artifacts["roots.txt"].decode("utf-8").splitlines()
    if not 0 < len(roots) <= MAX_NODES:
        raise QueryError("invalid root inventory size")
    native = full_native_inventory(artifacts["native.bep.json"], manifest.profile)
    reconcile_graph(graph, roots, native)
    return Bundle(
        manifest,
        sha256(canonical(manifest.model_dump(exclude_none=True))),
        anchor,
        graph,
        tuple(sorted(roots)),
        native,
    )


def pack(
    output: Path,
    profile: Profile,
    anchor_commit: str,
    artifacts: dict[str, bytes],
    *,
    capture_config_digest: str | None = None,
) -> Bundle:
    if set(artifacts) != set(LIMITS):
        raise QueryError("unsupported evidence member")
    if any(len(artifacts[name]) > limit for name, limit in LIMITS.items()):
        raise QueryError("evidence exceeds size limit")
    manifest = Manifest(
        anchor_commit=anchor_commit,
        profile=profile,
        artifacts={name: sha256(raw) for name, raw in artifacts.items()},
        capture_config_digest=capture_config_digest,
    )
    bundle = validate_artifacts(manifest, artifacts)
    # Never overwrite another capture. Publish the validated manifest last, so a
    # partial write cannot be mistaken for a complete evidence directory.
    output.mkdir(mode=0o700, exist_ok=False)
    for name in LIMITS:
        with (output / name).open("xb") as stream:
            stream.write(artifacts[name])
    with (output / "manifest.json").open("xb") as stream:
        stream.write(canonical(manifest.model_dump(exclude_none=True)))
    return bundle


def load(output: Path, expected_digest: str, expected_profile: Profile) -> Bundle:
    raw = read_bounded(output / "manifest.json", MAX_MANIFEST_BYTES)
    if sha256(raw) != expected_digest:
        raise QueryError("manifest identity mismatch")
    manifest = Manifest.model_validate(json.loads(raw, object_pairs_hook=unique_object))
    if canonical(manifest.model_dump(exclude_none=True)) != raw:
        raise QueryError("noncanonical evidence manifest")
    if manifest.profile != expected_profile:
        raise QueryError("repository or native profile mismatch")
    artifacts = {
        name: read_bounded(output / name, limit) for name, limit in LIMITS.items()
    }
    return validate_artifacts(manifest, artifacts)
