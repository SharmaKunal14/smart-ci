.PHONY: check schemas
check:
	uv run --frozen ruff format --check .
	uv run --frozen ruff check .
	uv run --frozen mypy
	uv run --frozen pytest
schemas:
	uv run --frozen python -c 'import json; from pathlib import Path; from smartci.cli import CONTRACTS; [Path("schemas", k+".v1.json").write_text(json.dumps(v.model_json_schema(), indent=2)+"\n") for k,v in CONTRACTS.items()]'

.PHONY: demo
demo:
	uv run --frozen python scripts/demo.py

.PHONY: polyglot-setup polyglot-demo
polyglot-setup:
	npm --prefix examples/polyglot/ts ci --ignore-scripts
	cd examples/polyglot/java && mvn -B -q -Dmaven.repo.local="$${SMARTCI_MAVEN_CACHE:-/tmp/smartci-m2}" test
polyglot-demo:
	npm --prefix examples/polyglot/ts run typecheck
	uv run --frozen python scripts/polyglot_demo.py

.PHONY: onboarding-setup onboarding-demo
onboarding-setup:
	uv run --frozen python scripts/packaging_pilot.py setup
onboarding-demo:
	uv run --frozen python scripts/packaging_pilot.py verify

.PHONY: shadow-demo
shadow-demo:
	uv run --frozen python scripts/shadow_demo.py
