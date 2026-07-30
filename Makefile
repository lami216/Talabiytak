.PHONY: install migrate run test lint format check
install:
	python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
init-db:
	.venv/bin/python -m app.cli init-db

check-db:
	.venv/bin/python -m app.cli check-db
run:
	.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
format:
	.venv/bin/ruff format .
lint:
	.venv/bin/ruff check .
test:
	.venv/bin/pytest
check: lint test
