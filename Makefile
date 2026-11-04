.PHONY: install api web worker migrate seed test lint demo banner-test web-test test-all

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e "apps/api[dev]" && pip install -e apps/worker
	cd apps/web && npm install
	cd packages/banner && npm install

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
	. .venv/bin/activate && ruff check apps/api/src apps/worker/src tests || true

demo: install migrate
	@echo "Run: make api   (terminal 1)"
	@echo "Run: make worker (terminal 2)"
	@echo "Run: make web   (terminal 3)"
	@echo "Open http://localhost:5173 — demo users *@demo.example.com / password123"
