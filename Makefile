.PHONY: help install install-dev test test-cov lint format type-check clean build upload docs

help:
	@echo "Available commands:"
	@echo "  install      Install package"
	@echo "  install-dev  Install with development dependencies"
	@echo "  test         Run tests"
	@echo "  test-cov     Run tests with coverage"
	@echo "  lint         Run linting"
	@echo "  format       Format code"
	@echo "  type-check   Run type checking"
	@echo "  clean        Clean build artifacts"
	@echo "  build        Build package"
	@echo "  upload       Upload to PyPI"
	@echo "  docs         Build documentation"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev,docs]"

test:
	pytest tests/

test-cov:
	pytest tests/ --cov=callpyback --cov-report=html --cov-report=term-missing

lint:
	flake8 callpyback/ tests/ examples/
	isort --check-only callpyback/ tests/ examples/
	black --check callpyback/ tests/ examples/

format:
	isort callpyback/ tests/ examples/
	black callpyback/ tests/ examples/

type-check:
	mypy callpyback/

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

build: clean
	python -m build

upload: build
	python -m twine upload dist/*

docs:
	cd docs && make html

# Development shortcuts
dev-setup: install-dev
	@echo "Development environment ready!"

check-all: format type-check lint test-cov
	@echo "All checks passed!"

# Run examples
run-basic:
	python examples/basic_usage.py

run-advanced:
	python examples/advanced_usage.py

# Quick test specific modules
test-core:
	pytest tests/test_basic.py -v

test-observers:
	pytest tests/ -k "observer" -v

test-state:
	pytest tests/ -k "state" -v
