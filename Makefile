PYTHON ?= python3.12
VENV ?= .venv
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest
TEST_DATABASE_URL ?= postgresql+psycopg://progress:progress@127.0.0.1:5432/progress_test

.PHONY: bootstrap db-up migrate seed-demo dev-api dev-web worker test-unit test-integration test-e2e evaluate build-web serve doctor remote-check native-smoke backup restore-verify
bootstrap:
	@command -v $(PYTHON) >/dev/null || (echo 'ERROR: Python 3.12 is required' >&2; exit 1)
	@$(PYTHON) -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"' || (echo 'ERROR: Python 3.12 is required; found:'; $(PYTHON) --version; exit 1)
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -e '.[dev]'
	@echo 'Bootstrap complete.'
db-up:
	docker compose up -d db
migrate:
	PYTHONPATH=backend $(VENV)/bin/alembic upgrade head
seed-demo:
	PYTHONPATH=backend $(VENV)/bin/python ops/seed_demo.py
dev-api:
	PYTHONPATH=backend $(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
dev-web:
	cd frontend && npm run dev
worker:
	PYTHONPATH=backend $(VENV)/bin/python ops/run_worker.py $(ARGS)
test-unit:
	$(PYTEST) backend/tests/unit
test-integration:
	PYTHONPATH=backend $(VENV)/bin/python ops/ensure_test_db.py
	DATABASE_URL=$(TEST_DATABASE_URL) PYTHONPATH=backend $(VENV)/bin/alembic upgrade head
	DATABASE_URL=$(TEST_DATABASE_URL) $(PYTEST) backend/tests/integration
test-e2e:
	cd frontend && npm run test:e2e
evaluate:
	PYTHONPATH=backend $(VENV)/bin/python -m evaluation.run $(ARGS)
build-web:
	cd frontend && npm run build
serve:
	PYTHONPATH=backend $(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
doctor:
	PYTHONPATH=backend $(VENV)/bin/python ops/doctor.py
remote-check:
	PYTHONPATH=backend $(VENV)/bin/python ops/remote_ollama_check.py $(ARGS)
native-smoke:
	PYTHONPATH=backend $(VENV)/bin/python ops/native_schedule_smoke.py --manifest data/references/native-import-manifest.json
backup:
	PYTHONPATH=backend $(VENV)/bin/python ops/backup.py $(ARGS)
restore-verify:
	PYTHONPATH=backend $(VENV)/bin/python ops/restore_verify.py $(ARGS)
