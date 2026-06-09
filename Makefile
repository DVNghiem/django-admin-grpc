.PHONY: help install test lint format docs docs-serve docs-build docs-deploy bump-version

help:
	@echo "Available targets:"
	@echo "  install       Install package in editable mode with dev dependencies"
	@echo "  test          Run the test suite with coverage"
	@echo "  lint          Run ruff linter and mypy type checker"
	@echo "  format        Run ruff formatter"
	@echo "  docs          Alias for 'docs-serve'"
	@echo "  docs-serve    Start MkDocs development server"
	@echo "  docs-build    Build the MkDocs documentation site"
	@echo "  docs-deploy   Deploy the site to GitHub Pages"
	@echo "  bump-version  Update package version: make bump-version VERSION=x.y.z"

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests
	mypy src/django_admin_grpc

format:
	ruff format src tests

docs: docs-serve

docs-serve:
	mkdocs serve

docs-build:
	mkdocs build

docs-deploy:
	mkdocs gh-deploy

# Bump the version across all source files.
# Usage: make bump-version VERSION=0.2.0
bump-version:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make bump-version VERSION=0.2.0"; \
		exit 1; \
	fi
	@echo "Bumping version to $(VERSION)..."
	@# Update pyproject.toml package version line
	@sed -i -E 's/^version = "[^"]+"$$/version = "$(VERSION)"/' pyproject.toml
	@# Update __init__.py package version line
	@sed -i -E 's/^__version__ = "[^"]+"$$/__version__ = "$(VERSION)"/' src/django_admin_grpc/__init__.py
	@# Update docs/getting-started/installation.md shell output version line only
	@sed -i -E "s/^'[0-9]+\.[0-9]+\.[0-9]+'$$/'$(VERSION)'/" docs/getting-started/installation.md
	@echo "Version bumped to $(VERSION) in:"
	@echo "  - pyproject.toml"
	@echo "  - src/django_admin_grpc/__init__.py"
	@echo "  - docs/getting-started/installation.md"
	@echo "Run 'git diff' to review changes."
