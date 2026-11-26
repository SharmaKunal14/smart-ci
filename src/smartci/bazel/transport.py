"""Retrieve native maps from a reviewed GitHub publisher, without executing code.

Publisher policy and capture configuration must come from trusted CI control
configuration. Hashes bind bytes; the approved workflow establishes provenance.
"""

import base64
import io
import json
import os
import stat
import struct
import subprocess
import threading
import time
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

from pydantic import Field, TypeAdapter

from smartci.ci.github import array_value, object_value

from .bundle import (
    LIMITS,
    MAX_MANIFEST_BYTES,
    Manifest,
    Revision,
    StrictModel,
    canonical,
    pack,
    read_bounded,
    sha256,
    validate_artifacts,
)
from .collection import CaptureConfig
from .events import unique_object
from .graph import QueryError

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_METADATA = 2 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MEMBERS = {
    "enrollment/collection.json": MAX_MANIFEST_BYTES,
    "enrollment/bundle/manifest.json": MAX_MANIFEST_BYTES,
    **{f"enrollment/bundle/{name}": limit for name, limit in LIMITS.items()},
}


class Publisher(StrictModel):
    schema_version: Literal["1"] = "1"
    repository: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$"
    )
    branch: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}$")
    workflow: str = Field(pattern=r"^\.github/workflows/[A-Za-z0-9_-]+\.ya?ml$")
    workflow_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    event: Literal["push", "workflow_dispatch"] = "push"
    artifact_prefix: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    max_age_seconds: int = Field(default=604800, ge=1, le=604800)


def api(route: str) -> bytes:
    """Bound time and output while reading, including on an oversized response."""
    limit = MAX_ARCHIVE if route.endswith("/zip") else MAX_METADATA
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
        if key in os.environ
    }
    with subprocess.Popen(
        ["gh", "api", "--hostname", "github.com", route],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**environment, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"},
    ) as process:
        assert process.stdout is not None
        timer = threading.Timer(45, process.kill)
        timer.start()
        try:
            raw = process.stdout.read(limit + 1)
            if len(raw) > limit:
                raise QueryError("GitHub response exceeds size limit")
            if process.wait() != 0:
                raise QueryError("GitHub evidence unavailable")
            return raw
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            timer.cancel()
            timer.join()


def parse_object(raw: bytes, limit: int = MAX_METADATA) -> dict[str, object]:
    if len(raw) > limit:
        raise QueryError("metadata exceeds size limit")
    return object_value(json.loads(raw, object_pairs_hook=unique_object))


def timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise QueryError("invalid artifact timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise QueryError("artifact timestamp lacks timezone")
    return parsed.timestamp()


def unpack(raw: bytes) -> dict[str, bytes]:
    """Read a fixed set of files; never extract archive paths onto the filesystem."""
    if len(raw) > MAX_ARCHIVE:
        raise QueryError("archive exceeds size limit")
    # Check the fixed ZIP end record before ZipFile allocates central-directory
    # objects. ZIP64/multi-volume archives are unnecessary at these size limits.
    end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if end < 0 or len(raw) - end < 22:
        raise QueryError("missing ZIP end record")
    _, disk, central_disk, disk_count, count, size, offset, comment = (
        struct.unpack_from("<4s4H2IH", raw, end)
    )
    if (
        disk != 0
        or central_disk != 0
        or disk_count != count
        or count > 256
        or size > MAX_METADATA
        or offset + size != end
        or end + 22 + comment != len(raw)
    ):
        raise QueryError("unsupported or oversized ZIP directory")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(entries) > 256
            or len(set(names)) != len(names)
            or not MEMBERS.keys() <= set(names)
            or sum(entry.file_size for entry in entries) > MAX_EXPANDED
        ):
            raise QueryError("invalid evidence archive inventory")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or "\x00" in entry.orig_filename
                or path.as_posix() != entry.filename.rstrip("/")
                or entry.flag_bits & 1
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
            ):
                raise QueryError("unsafe evidence archive entry")
        payloads = {}
        for name, limit in MEMBERS.items():
            entry = archive.getinfo(name)
            if (
                entry.is_dir()
                or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                or entry.file_size > limit
            ):
                raise QueryError("invalid evidence member")
            with archive.open(entry) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise QueryError("evidence member exceeds limit")
            payloads[name] = data
    return payloads


def validate_capture(
    payloads: dict[str, bytes], revision: str, config: CaptureConfig
) -> tuple[Manifest, dict[str, bytes]]:
    manifest_raw = payloads["enrollment/bundle/manifest.json"]
    manifest = Manifest.model_validate(parse_object(manifest_raw))
    collection = parse_object(payloads["enrollment/collection.json"])
    config_digest = sha256(canonical(config.model_dump()))
    if (
        canonical(manifest.model_dump(exclude_none=True)) != manifest_raw
        or manifest.profile != config.profile
        or manifest.capture_config_digest != config_digest
        or collection.get("schema_version") != "smartci.bazel-collection.v1"
        or collection.get("status") != "ready"
        or collection.get("revision") != revision
        or collection.get("map_revision") != manifest.anchor_commit
        or collection.get("config_digest") != config_digest
        or collection.get("manifest_digest") != sha256(manifest_raw)
        or "error" in collection
    ):
        raise QueryError("collection identity mismatch")
    if collection.get("cache") == "reused":
        if (
            "native_exit" not in collection
            or "query_exit" not in collection
            or collection.get("native_exit") is not None
            or collection.get("query_exit") is not None
        ):
            raise QueryError("invalid reuse receipt")
    elif collection.get("cache") in ("not_supplied", "rejected"):
        if manifest.anchor_commit != revision or any(
            type(collection.get(key)) is not int or collection[key] != 0
            for key in ("native_exit", "query_exit")
        ):
            raise QueryError("invalid fresh collection receipt")
    else:
        raise QueryError("unknown collection mode")
    evidence = {name: payloads[f"enrollment/bundle/{name}"] for name in LIMITS}
    bundle = validate_artifacts(manifest, evidence)
    if any(
        type(collection.get(key)) is not int or collection[key] != count
        for key, count in (
            ("native_test_targets", len(bundle.native.tests)),
            ("native_build_only_targets", len(bundle.native.build_only)),
        )
    ):
        raise QueryError("collection inventory mismatch")
    return manifest, evidence


def fetch(
    publisher: Publisher,
    revision: str,
    config: CaptureConfig,
    output: Path,
    *,
    request: Callable[[str], bytes] = api,
    now: float | None = None,
) -> dict[str, object]:
    # Use the manifest's revision validator before constructing an API route.
    TypeAdapter(Revision).validate_python(revision, strict=True)
    if publisher.repository != config.profile.repository or output.exists():
        raise QueryError("publisher mismatch or output already exists")
    prefix = f"repos/{publisher.repository}"
    definition = parse_object(
        request(f"{prefix}/contents/{publisher.workflow}?ref={revision}")
    )
    content = definition.get("content")
    if (
        definition.get("encoding") != "base64"
        or definition.get("type") != "file"
        or not isinstance(content, str)
        or sha256(base64.b64decode("".join(content.split()), validate=True))
        != publisher.workflow_digest
    ):
        raise QueryError("publisher workflow is not approved")
    workflow = quote(publisher.workflow.rsplit("/", 1)[1], safe="")
    runs = parse_object(
        request(
            f"{prefix}/actions/workflows/{workflow}/runs?event={publisher.event}"
            f"&status=success&head_sha={revision}&per_page=20"
        )
    )
    clock = time.time() if now is None else now
    checked_runs = 0
    for item in array_value(runs.get("workflow_runs"))[:20]:
        run = object_value(item)
        if (
            run.get("event") != publisher.event
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("head_sha") != revision
            or run.get("head_branch") != publisher.branch
            or run.get("path") != publisher.workflow
            or object_value(run.get("repository")).get("full_name")
            != publisher.repository
            or object_value(run.get("head_repository")).get("full_name")
            != publisher.repository
            or type(run.get("id")) is not int
            or type(run.get("run_attempt")) is not int
        ):
            continue
        run_id, attempt = run["id"], run["run_attempt"]
        if not isinstance(run_id, int) or not isinstance(attempt, int):
            raise QueryError("invalid run identity")
        if run_id <= 0 or attempt <= 0:
            continue
        checked_runs += 1
        if checked_runs > 3:
            break
        candidates = parse_object(
            request(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")
        )
        items = array_value(candidates.get("artifacts"))
        if len(items) > 100:
            raise QueryError("artifact listing exceeds requested limit")
        artifacts = [object_value(a) for a in items]
        matches = [
            a
            for a in artifacts[:100]
            if a.get("name") == f"{publisher.artifact_prefix}-{attempt}"
        ]
        if len(matches) != 1:
            continue
        artifact = matches[0]
        if (
            artifact.get("expired") is not False
            or not 0
            <= clock - timestamp(artifact.get("created_at"))
            <= publisher.max_age_seconds
            or timestamp(artifact.get("expires_at")) <= clock
        ):
            continue
        size, artifact_id = artifact.get("size_in_bytes"), artifact.get("id")
        origin = object_value(artifact.get("workflow_run"))
        if (
            type(artifact_id) is not int
            or not isinstance(artifact_id, int)
            or artifact_id <= 0
            or type(size) is not int
            or not isinstance(size, int)
            or not 0 < size <= MAX_ARCHIVE
            or type(origin.get("id")) is not int
            or origin.get("id") != run_id
            or origin.get("head_sha") != revision
            or origin.get("head_branch") != publisher.branch
        ):
            raise QueryError("invalid artifact origin or size")
        raw = request(f"{prefix}/actions/artifacts/{artifact_id}/zip")
        if len(raw) > MAX_ARCHIVE or artifact.get("digest") != "sha256:" + sha256(raw):
            raise QueryError("artifact digest mismatch")
        manifest, evidence = validate_capture(unpack(raw), revision, config)
        config_digest = sha256(canonical(config.model_dump()))
        receipt: dict[str, object] = {
            "schema_version": "smartci.bazel-fetch.v1",
            "status": "ready",
            "repository": publisher.repository,
            "revision": revision,
            "map_revision": manifest.anchor_commit,
            "run_id": run_id,
            "run_attempt": attempt,
            "artifact_id": artifact_id,
            "archive_digest": sha256(raw),
            "manifest_digest": sha256(
                canonical(manifest.model_dump(exclude_none=True))
            ),
            "publisher_digest": sha256(canonical(publisher.model_dump())),
            "config_digest": config_digest,
        }
        # Publish only validated evidence; a partial directory has no ready receipt.
        output.mkdir(mode=0o700, exist_ok=False)
        pack(
            output / "bundle",
            config.profile,
            manifest.anchor_commit,
            evidence,
            capture_config_digest=config_digest,
        )
        (output / "fetch.json").write_bytes(canonical(receipt))
        return receipt
    raise QueryError("no trusted map for the requested revision")


def read_publisher(path: Path) -> Publisher:
    return Publisher.model_validate(
        parse_object(read_bounded(path, MAX_MANIFEST_BYTES), MAX_MANIFEST_BYTES)
    )
