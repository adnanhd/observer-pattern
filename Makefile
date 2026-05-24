.PHONY: help install install-dev test test-cov lint format type-check clean build upload docs

help:
	@echo "make targets:"
	@echo "  install      pip-install the package"
	@echo "  install-dev  pip-install with [dev] extras"
	@echo "  test         pytest"
	@echo "  test-cov     pytest + coverage report"
	@echo "  lint         ruff check + black --check"
	@echo "  format       black + ruff --fix"
	@echo "  type-check   mypy + pyright"
	@echo "  clean        remove build artefacts"
	@echo "  build        build sdist + wheel"
	@echo "  upload       twine upload dist/*"
	@echo "  docs         build sphinx docs"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev,docs]"

test:
	pytest tests/

test-cov:
	pytest tests/ --cov=eventforge --cov-report=html --cov-report=term-missing

lint:
	ruff check eventforge/ tests/ examples/
	black --check eventforge/ tests/ examples/

format:
	black eventforge/ tests/ examples/
	ruff check --fix eventforge/ tests/ examples/

type-check:
	mypy eventforge/
	-pyright eventforge/

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

build: clean
	python -m build

upload: build
	python -m twine upload dist/*

docs:
	cd docs && make html

check-all: format type-check lint test-cov
	@echo "All checks passed."
