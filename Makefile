.PHONY: install test lint fmt run clean

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

install:
	python3 -m venv .venv && $(PIP) install --disable-pip-version-check -r backend/requirements.txt

test:
	cd backend && $(PYTHON) -m pytest tests/ -v

lint:
	cd backend && $(PYTHON) -m ruff check .

fmt:
	cd backend && $(PYTHON) -m ruff check . --fix

run:
	cd backend && $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

clean:
	find backend -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find backend -name '.pytest_cache' -type d -exec rm -rf {} + 2>/dev/null || true
