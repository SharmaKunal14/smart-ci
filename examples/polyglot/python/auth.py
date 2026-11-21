"""Tiny auth contract consumed by the TypeScript checkout component."""

import json
import sys


def issue(role: str) -> dict[str, str]:
    if role not in {"buyer", "admin"}:
        raise ValueError("invalid role")
    return {"role": role}


if __name__ == "__main__":
    print(json.dumps(issue(sys.argv[1])))
