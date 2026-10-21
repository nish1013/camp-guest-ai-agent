.PHONY: lint format test test-int evals e2e

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest tests/unit

test-int:
	uv run pytest tests/integration

evals:
	uv run python -m tests.evals.run_evals

e2e:
	uv run playwright install chromium
	uv run pytest tests/e2e
