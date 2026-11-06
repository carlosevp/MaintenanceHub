.PHONY: install api web worker migrate seed test lint demo demo-essentials demo-team demo-enterprise demo-stop banner-test web-test test-all compose-up compose-down compose-reset

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e "apps/api[dev]" && pip install -e apps/worker
	cd apps/web && npm install
	cd packages/banner && npm install

# Lightweight local (SQLite) — no Docker required
api:
	mkdir -p data
	. .venv/bin/activate && \
	  ENVIRONMENT=development AUTH_MODE=local_dev SEED_DEMO_DATA=true \
	  DATABASE_URL=sqlite:///./data/maintenancehub.db \
	  uvicorn maintenancehub_api.main:app --reload --app-dir apps/api/src --host 0.0.0.0 --port 8000

web:
	cd apps/web && npm run dev

worker:
	. .venv/bin/activate && \
	  DATABASE_URL=sqlite:///./data/maintenancehub.db \
	  PYTHONPATH=apps/api/src:apps/worker/src \
	  python -m maintenancehub_worker.main

migrate:
	. .venv/bin/activate && \
	  DATABASE_URL=$${DATABASE_URL:-sqlite:///./data/maintenancehub.db} \
	  alembic -c db/alembic.ini upgrade head

seed:
	. .venv/bin/activate && \
	  DATABASE_URL=$${DATABASE_URL:-sqlite:///./data/maintenancehub.db} \
	  PYTHONPATH=apps/api/src python scripts/seed_demo.py

test:
	. .venv/bin/activate && \
	  PYTHONPATH=apps/api/src \
	  ENVIRONMENT=development AUTH_MODE=local_dev SEED_DEMO_DATA=false \
	  pytest tests -q

banner-test:
	cd packages/banner && npm install && npm test && npm run build

web-test:
	cd apps/web && npm test

test-all: test banner-test web-test

lint:
	. .venv/bin/activate && ruff check apps/api/src apps/worker/src tests --config apps/api/pyproject.toml

# Integrated stack (Postgres + api + worker + web)
compose-up:
	docker compose up --build -d

# Preserve named volumes (Postgres data) by default
compose-down:
	docker compose down

# Destructive: remove containers AND volumes
compose-reset:
	docker compose down -v

# Default demo = Essentials (synthetic data, local auth, captured notifications)
demo:
	@EXPERIENCE_PROFILE=essentials ./scripts/demo.sh

demo-essentials:
	@EXPERIENCE_PROFILE=essentials ./scripts/demo.sh

demo-team:
	@EXPERIENCE_PROFILE=team ./scripts/demo.sh

demo-enterprise:
	@EXPERIENCE_PROFILE=enterprise ./scripts/demo.sh

demo-stop:
	@-kill $$(cat data/demo-api.pid data/demo-worker.pid data/demo-web.pid 2>/dev/null) 2>/dev/null || true
	@echo "Demo processes signaled to stop"
