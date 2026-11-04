# MaintenanceHub

Internal **Maintenance & Outage Communication Platform**.

This is **not** a monitoring product. Status is published by people (planned maintenance, extensions, manual outages). Platform `/healthz` and `/readyz` exist only for pod liveness/readiness.

Architecture source of truth lives in the Project store docs (PRD, ADRs, data model, API contracts, milestone plan). This repository implements milestones **M0 → M8** (recurrence expansion M3b still partial — see [docs/LIMITATIONS.md](docs/LIMITATIONS.md)).

## Stack

- **API:** Python FastAPI + SQLAlchemy + Alembic  
- **Web:** React + TypeScript + Vite + Tailwind (shadcn-style components)  
- **Worker:** Stub until M5 (DB outbox/jobs already written)  
- **DB:** SQLite local / Postgres-ready  

## Quick start (local)

```bash
# 1) Python env + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e "apps/api[dev]"
pip install -e apps/worker

# 2) Env
cp .env.example .env
mkdir -p data

# 3) Migrate (or rely on create_all on API boot for SQLite demo)
export DATABASE_URL=sqlite:///./data/maintenancehub.db
export ENVIRONMENT=development
export AUTH_MODE=local_dev
export SEED_DEMO_DATA=true
alembic -c db/alembic.ini upgrade head   # after first migration is generated
# optional: python scripts/seed_demo.py

# 4) API
uvicorn maintenancehub_api.main:app --reload --app-dir apps/api/src --host 0.0.0.0 --port 8000

# 5) Worker (other terminal) — required for notifications
PYTHONPATH=apps/api/src:apps/worker/src \
  python -m maintenancehub_worker.main

# 6) Web (other terminal)
cd apps/web && npm install && npm run dev
```

Open http://localhost:5173

### Test a notification (log sink when `SMTP_ENABLED=false`)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"publisher@demo.example.com","password":"password123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://localhost:8000/api/v1/notifications/test \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"template_key":"event.created","destination_type":"email_address","destination":"you@example.com"}'
```

Worker also drains outbox on lifecycle transitions and sends subscription deliveries (watch worker logs for `[SMTP_DISABLED log sink]`).

### Demo logins (seeded)

| Email | Password | Role |
|-------|----------|------|
| `viewer@demo.example.com` | `password123` | viewer |
| `publisher@demo.example.com` | `password123` | publisher |
| `owner@demo.example.com` | `password123` | application_owner |
| `admin@demo.example.com` | `password123` | platform_administrator |

All demo titles are prefixed with `[DEMO]`.

## Make targets

```bash
make install   # venv + pip + npm
make api       # API on :8000
make web       # Vite on :5173
make worker    # worker stub
make test      # pytest
make migrate   # alembic upgrade head
```

## Docker Compose

```bash
docker compose up --build
```

- API: http://localhost:8000  
- Web: http://localhost:8080  
- Optional Postgres: `docker compose --profile postgres up`

## Tests

```bash
source .venv/bin/activate
PYTHONPATH=apps/api/src ENVIRONMENT=development AUTH_MODE=local_dev SEED_DEMO_DATA=false pytest tests -q
```

Critical coverage in this slice: lifecycle state machine, API authz deny paths, event transitions/extend, SQLite schema/idempotency uniques, fail-closed `local_dev` in production.

## Milestone acceptance

| Milestone | Met? |
|-----------|------|
| M0 Bootstrap, healthz/readyz, Docker, compose | Yes |
| M1 Core schema + portable migrations + seed | Yes |
| M2 Catalog CRUD + RBAC read/write + deps origin | Yes |
| M3 One-time scheduling, lifecycle, approval_state, timeline | Yes |
| M3b Recurrence expansion | **Partial** (schema + ICS RRULE emit; calendar expansion incomplete) |
| M4 Dashboard, calendar day/week/month, favorites, accessible status | Yes |
| M5 Durable jobs (outbox/lease/retry) | Yes |
| M6 Subscriptions + SMTP/log notifications + dedupe | Yes (digests schema-only) |
| M7 Power Automate email bridge destinations | Yes |
| M8 Personalized ICS + revocable tokens | Yes |

Deferred: M9+ (ServiceNow, CSV CMDB, enterprise OIDC/LDAP wiring, banner). See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Auth safety

- `AUTH_MODE=local_dev` is **refused** when `ENVIRONMENT` is `staging` or `production` unless `ALLOW_LOCAL_AUTH=true` (audited break-glass).
- Deployed environments must set `AUTH_MODE=oidc` or `ldap` (providers stubbed until M11).

## API docs

With the API running: http://localhost:8000/docs
