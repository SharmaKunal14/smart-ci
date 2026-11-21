"""Atomic report publication; Markdown embeds escaped structured data."""

import html
import json
import os
import tempfile
from pathlib import Path

from .selection import Report


def markdown(report: Report) -> str:
    data = json.dumps(report.model_dump(), indent=2, sort_keys=True)
    return (
        f"# Smart CI audit\n\nProposed mode: **{report.mode}**. "
        f"Required execution: **{report.execution}**.\n\n"
        "Full execution means the independent full-suite command, not the IDs below. "
        "Omissions are conditional on the supplied evidence; they are not safety guarantees.\n\n"
        f"<pre>{html.escape(data)}</pre>\n"
    )


def atomic_write(path: Path, content: str) -> None:
    name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)
