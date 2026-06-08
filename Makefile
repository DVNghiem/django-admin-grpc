.PHONY: help install test lint format docs docs-serve docs-build docs-deploy

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
