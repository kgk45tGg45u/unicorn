PY = .venv/bin/python

.PHONY: setup check test run migrate defaults jobs

setup:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

check:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	$(PY) manage.py check
	$(PY) manage.py makemigrations --check --dry-run
	.venv/bin/pytest -q

test:
	.venv/bin/pytest -q

run:
	$(PY) manage.py runserver 127.0.0.1:8000

migrate:
	$(PY) manage.py migrate
	$(PY) manage.py loaddata contracts

defaults:
	$(PY) manage.py load_defaults

jobs:
	$(PY) manage.py run_jobs
