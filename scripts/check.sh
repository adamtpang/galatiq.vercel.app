#!/usr/bin/env bash
# Lint, type check and the offline test suite. Same commands as `make check`; CI runs them through pytest
# (tests/test_static_checks.py), since the workflow file installs requirements.txt and runs pytest.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m ruff check --isolated --select E4,E7,E9,F .
python -m mypy invoice_agents main.py --ignore-missing-imports
env -u XAI_API_KEY python -m pytest -q
