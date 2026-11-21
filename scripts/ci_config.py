"""Materialize the pinned tool's reviewed policy for an enrolled repository."""

import argparse
import json
from pathlib import Path

from smartci.ci.models import Context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context = Context.model_validate_json(args.context.read_bytes())
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "examples/onboarding/packaging"
    for name in ("config.json", "policy.json"):
        data = json.loads((source / name).read_bytes())
        data["repository"] = context.repository
        (args.output / name).write_text(json.dumps(data) + "\n")
    # Linux baseline publication permits no skipped cases.
    (args.output / "shadow.json").write_text('{"schema_version":"1"}\n')


if __name__ == "__main__":
    main()
