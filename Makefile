.PHONY: help init lint test coverage

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  init      Initialize environment and set up git hooks"
	@echo "  lint      Run ruff check linter"
	@echo "  test      Run pytest unit/integration tests"
	@echo "  coverage  Run tests and print diff coverage report"
	@echo "  help      Show this help message"

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
