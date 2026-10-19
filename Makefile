.PHONY: lint format test test-int

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
