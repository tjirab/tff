.PHONY: help init lint test coverage docs-serve docs-build demos

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  init        Initialize environment and set up git hooks"
	@echo "  lint        Run ruff check linter"
	@echo "  test        Run pytest unit/integration tests"
	@echo "  coverage    Run tests and print diff coverage report"
	@echo "  docs-serve  Run local documentation server"
	@echo "  docs-build  Build documentation in strict mode"
	@echo "  demos       Regenerate animated VHS terminal demo GIFs"
	@echo "  help        Show this help message"

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

docs-serve:
	uv run --group docs mkdocs serve

docs-build:
	uv run --group docs mkdocs build --strict

demos:
	./demos/generate_demos.sh
