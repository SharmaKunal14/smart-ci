"""Initial live pilot only permits source commits present in a public GitHub repo."""

import json
import re

from .http import Transport
from .models import Inputs


def validate_public_scope(inputs: Inputs, transport: Transport) -> None:
    repository = inputs.changes.repository
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository
    ):
        raise ValueError("GitHub repository required")
    response = transport.request("GET", f"/repos/{repository}")
    if response.status != 200:
        raise ValueError("public repository not verified")
    value = json.loads(response.body)
    if (
        not isinstance(value, dict)
        or value.get("private") is not False
        or not isinstance(value.get("full_name"), str)
        or value.get("full_name", "").lower() != repository.lower()
    ):
        raise ValueError("public repository not verified")
    for commit in sorted(inputs.sources):
        response = transport.request("GET", f"/repos/{repository}/commits/{commit}")
        value = json.loads(response.body) if response.status == 200 else None
        if not isinstance(value, dict) or value.get("sha") != commit:
            raise ValueError("public commit not verified")
