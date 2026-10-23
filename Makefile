check:
	bash scripts/check.sh

lint:
	python -m ruff check --isolated --select E4,E7,E9,F .

typecheck:
	python -m mypy invoice_agents main.py --ignore-missing-imports

.PHONY: check lint typecheck
