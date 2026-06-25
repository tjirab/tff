.PHONY: init lint test coverage

init:
	uv sync --extra dev
	git config core.hooksPath .githooks

lint:
	uv run ruff check .

test:
	uv run pytest

coverage:
	uv run pytest --cov=src --cov-report=xml
	uv run diff-cover coverage.xml --compare-branch=origin/main
