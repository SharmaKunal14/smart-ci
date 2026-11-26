"""Experimental runtime-entry candidates. Never a production execution plan.

Only a separate, required native full run can validate this shadow hypothesis.
Source readers, callbacks, shared state and unobserved code remain unresolved.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from smartci.contracts import Digest, TestUnit
from smartci.git_changes import changes_from_git, git
from smartci.selection import digest

from .change_scope import compare

OBSERVER_FILE = Path(__file__).parents[1] / "adapters" / "runtime_observer.py"


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Context(Strict):
    code_entries: list[str] = Field(default_factory=list, max_length=500_000)
    code_files: list[str] = Field(default_factory=list, max_length=100_000)
    open_attempts: list[str] = Field(default_factory=list, max_length=100_000)
    import_requests: list[str] = Field(default_factory=list, max_length=100_000)
    process_events: list[Literal["CHILD_PROCESS_ATTEMPT"]] = Field(
        default_factory=list, max_length=1
    )


class Metadata(Strict):
    kind: Literal["collection", "fixture_setup"]
    scope: Literal["function", "class", "module", "package", "session"]
    owner: str = Field(max_length=1024)


class ObservedRun(Strict):
    schema_: Literal["smartci.runtime-observation.v2"] = Field(alias="schema")
    engine: Literal["monitoring"]
    complete: Literal[False]
    omission_authorized: Literal[False]
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    python: str
    platform: str
    implementation: str
    pytest: str
    observer_sha256: Digest
    tracked_blobs: dict[str, str] = Field(max_length=100_000)
    test_files: list[str] = Field(min_length=1, max_length=10_000)
    case_count: int = Field(gt=0, le=100_000)
    exit_code: Literal[0]
    plugins: list[str] = Field(max_length=1000)
    diagnostics: list[str] = Field(max_length=1000)
    limitations: list[str] = Field(max_length=100)
    contexts: dict[str, Context] = Field(max_length=100_000)
    context_metadata: dict[str, Metadata] = Field(max_length=100_000)
    digest: Digest

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        if (
            len(self.test_files) != len(set(self.test_files))
            or not set(self.test_files) <= self.tracked_blobs.keys()
        ):
            raise ValueError("invalid observed test inventory")
        for path in self.tracked_blobs:
            TestUnit.relative_path(path)
        count = 0
        for context in self.contexts.values():
            for path in [*context.code_files, *context.open_attempts]:
                if path not in self.tracked_blobs:
                    raise ValueError("observed path outside tracked tree")
            for entry in context.code_entries:
                path, _, line = entry.rpartition(":")
                if (
                    path not in self.tracked_blobs
                    or not line.isascii()
                    or not line.isdecimal()
                    or not 1 <= int(line) <= 100_000
                ):
                    raise ValueError("invalid observed code entry")
            count += sum(len(values) for values in context.model_dump().values())
        if count > 500_000:
            raise ValueError("observation exceeds entry limit")
        return self


class Span(Strict):
    entry_line: int = Field(ge=1, le=100_000)
    end_line: int = Field(ge=1, le=100_000)
    body_digest: Digest


class BodyChange(Strict):
    name: str
    occurrence: int
    base: Span
    head: Span
    decorated: bool
    class_member: bool


def tree(root: Path, revision: str) -> dict[str, str]:
    result = {}
    for item in git(root, "--no-replace-objects", "ls-tree", "-rz", revision).split(
        b"\0"
    ):
        if not item:
            continue
        metadata, path_raw = item.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        path = TestUnit.relative_path(path_raw.decode())
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("unsupported source tree")
        result[path] = blob
    return result


def candidate(
    root: Path, base: str, head: str, raw: bytes, must_run: list[str] | None = None
) -> dict[str, object]:
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("observation exceeds byte limit")
    data = json.loads(raw)
    if not isinstance(data, dict) or digest(
        {k: v for k, v in data.items() if k != "digest"}
    ) != data.get("digest"):
        raise ValueError("observation digest mismatch")
    observed = ObservedRun.model_validate(data)
    if observed.commit != base or observed.tracked_blobs != tree(root, base):
        raise ValueError("observation does not bind exact base tree")
    if (
        observed.observer_sha256
        != hashlib.sha256(OBSERVER_FILE.read_bytes()).hexdigest()
    ):
        raise ValueError("observer implementation mismatch")
    if any(
        code
        not in {
            "CHILD_PROCESS_NOT_OBSERVED",
            "UNTRACKED_OR_EXTERNAL_OPENS_NOT_ATTRIBUTED",
        }
        for code in observed.diagnostics
    ):
        raise ValueError("observation incomplete or unstable")
    changes = changes_from_git(root, base, head, "runtime-shadow/experiment")
    if changes.base != base or not changes.paths:
        raise ValueError("exact changed comparison required")
    all_tests = set(observed.test_files)
    selected = set(must_run or [])
    if not selected <= all_tests:
        raise ValueError("mandatory test outside inventory")
    head_tree = tree(root, head)
    scopes = []
    entries: dict[str, str] = {}
    fallback = []
    for path in changes.paths:
        if (
            not path.endswith(".py")
            or path not in observed.tracked_blobs
            or path not in head_tree
            or path in all_tests
        ):
            fallback.append("UNSUPPORTED_CHANGE")
            continue
        blobs = []
        for revision in (base, head):
            obj = f"{revision}:{path}"
            if int(git(root, "--no-replace-objects", "cat-file", "-s", obj)) > 262_144:
                raise ValueError("source exceeds inspection limit")
            blobs.append(git(root, "--no-replace-objects", "cat-file", "blob", obj))
        scope = compare(path, *blobs)
        scopes.append(scope)
        if (
            scope["classification"] != "function_body_only"
            or scope["callables_truncated"]
        ):
            fallback.append("NOT_BODY_ONLY")
            continue
        for change in TypeAdapter(list[BodyChange]).validate_python(
            scope["changed_callables"]
        ):
            entries[f"{path}:{change.base.entry_line}"] = change.name

    def owners(context: str) -> set[str]:
        if context in all_tests:
            return {context}
        metadata = observed.context_metadata.get(context)
        if metadata:
            if (
                metadata.scope in {"function", "class", "module"}
                and metadata.owner in all_tests
            ):
                return {metadata.owner}
            if metadata.scope == "package" and metadata.owner != ".":
                TestUnit.relative_path(metadata.owner)
                return {
                    p for p in all_tests if p.startswith(metadata.owner + "/")
                } or all_tests
        return all_tests

    witnesses = []
    seen = set()
    reads = []
    processes = []
    for context, values in sorted(observed.contexts.items()):
        hits = sorted(set(values.code_entries) & entries.keys())
        if hits:
            selected.update(owners(context))
            seen.update(hits)
            witnesses.append({"context": context, "entries": hits})
        if set(values.open_attempts) & set(changes.paths):
            reads.append(context)
        if values.process_events:
            processes.append(context)
            selected.update(owners(context))
    if "CHILD_PROCESS_NOT_OBSERVED" in observed.diagnostics and not processes:
        fallback.append("PROCESS_CALLER_NOT_RECORDED")
    if not selected:
        fallback.append("NO_OBSERVED_CANDIDATES")
    if fallback:
        selected = all_tests
    result = {
        "schema_version": "smartci.runtime-shadow-candidate.v1",
        "comparison": {"base": base, "head": head},
        "observation_digest": observed.digest,
        "required_execution": "full",
        "omission_authorized": False,
        "candidate_files": sorted(selected),
        "inventory_files": sorted(all_tests),
        "fallback": sorted(set(fallback)),
        "unobserved_changed_callables": sorted(
            entries[key] for key in entries.keys() - seen
        ),
        "unresolved_source_read_contexts": reads,
        "retained_process_contexts": processes,
        "witnesses": witnesses,
        "scopes": scopes,
        "uncertainties": observed.limitations,
        "diagnostics": observed.diagnostics,
        "model_calls": 0,
        "purpose": "shadow_hypothesis_requires_independent_full_suite",
    }
    return result | {"digest": digest(result)}
