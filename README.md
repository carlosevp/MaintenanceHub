# MaintenanceHub

Internal **Maintenance & Outage Communication Platform**.

This is **not** a monitoring product. Status is published by people (planned maintenance, extensions, manual outages). Platform `/healthz` and `/readyz` exist only for pod liveness/readiness.

Architecture source of truth lives in the Project store docs (PRD, ADRs, data model, API contracts, milestone plan). This repository implements milestones **M0 → M13** (recurrence expansion **M3b** still partial — see [docs/LIMITATIONS.md](docs/LIMITATIONS.md)).

## Stack

- **API:** Python FastAPI + SQLAlchemy + Alembic  
- **Web:** React + TypeScript + Vite + Tailwind  
- **Worker:** DB outbox / lease job runner  
- **Banner:** `@maintenancehub/banner` embed package (`packages/banner`)  
- **DB:** SQLite local / Postgres for multi-replica  

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

# 3) Migrate
export DATABASE_URL=sqlite:///./data/maintenancehub.db
export ENVIRONMENT=development
export AUTH_MODE=local_dev
export SEED_DEMO_DATA=true
alembic -c db/alembic.ini upgrade head

# 4) API (seeds [DEMO] data on boot when SEED_DEMO_DATA=true)
uvicorn maintenancehub_api.main:app --reload --app-dir apps/api/src --host 0.0.0.0 --port 8000

# 5) Worker (other terminal) — required for notifications
PYTHONPATH=apps/api/src:apps/worker/src \
  python -m maintenancehub_worker.main

# 6) Web (other terminal)
cd apps/web && npm install && npm run dev
```

Or: `make install && make migrate` then `make api` / `make worker` / `make web`.

Open http://localhost:5173 — Banner demo at `/banner-demo`, limitations at `/about`.

### Demo logins (seeded)

| Email | Password | Role |
|-------|----------|------|
| `viewer@demo.example.com` | `password123` | viewer |
| `publisher@demo.example.com` | `password123` | publisher |
| `owner@demo.example.com` | `password123` | application_owner |
| `admin@demo.example.com` | `password123` | platform_administrator |

All demo titles are prefixed with `[DEMO]`. Seed includes apps (`payments-gateway`, `hr-portal`, `inventory-svc`), tags, a manual dependency, favorites, current/upcoming/recent events, and a manual outage.

### Banner package

```bash
cd packages/banner && npm install && npm test && npm run build
```

Usage: [packages/banner/README.md](packages/banner/README.md). API: `GET /api/v1/public/banner?application_key=…` with a JWT that has scope `banner:read` (service credential) or a publisher/admin user.

### Service credential for embeds

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@demo.example.com","password":"password123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://localhost:8000/api/v1/admin/service-credentials \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"banner-embed","scopes":["banner:read"]}'
# then POST /api/v1/auth/service/token with client_id + client_secret
```

## Make targets

```bash
make install    # venv + pip + npm (web + banner)
make api        # API on :8000
make web        # Vite on :5173
make worker     # job worker
make test       # pytest
make banner-test
make web-test
make test-all
make migrate
```

## Docker Compose (integrated: web + api + worker + Postgres)

```bash
docker compose up --build
# or: make compose-up
```

- Web: http://localhost:8080 (proxies `/api` via `API_UPSTREAM`)
- API: http://localhost:8000  
- Postgres: localhost:5432 (`mh` / `mh` / `maintenancehub`)
- Migrations run once via the `migrate` service before API/worker start

Images run as non-root UID **10001**. For lightweight SQLite without Docker, use the Makefile targets above.

## Audit

See [docs/IMPLEMENTATION_AUDIT.md](docs/IMPLEMENTATION_AUDIT.md) for the requirement→implementation map and remaining gaps.

## OpenShift

See [docs/deploy-openshift.md](docs/deploy-openshift.md). Manifests: `deploy/openshift/` (api, worker, web, kustomization). Use Postgres; set `AUTH_MODE=oidc|ldap`; never leave `SEED_DEMO_DATA=true` in production.

## Tests

```bash
source .venv/bin/activate
PYTHONPATH=apps/api/src ENVIRONMENT=development AUTH_MODE=local_dev SEED_DEMO_DATA=false pytest tests -q
cd packages/banner && npm test
cd apps/web && npm test
```

## Milestone acceptance

| Milestone | Met? |
|-----------|------|
| M0–M4 Bootstrap, catalog, scheduling, dashboard | Yes |
| M3b Recurrence expansion | **Partial** (schema + ICS RRULE; calendar expansion incomplete) |
| M5–M8 Jobs, notify, bridge, ICS | Yes |
| M9 ServiceNow poll | Yes (fixture/null by default) |
| M10 CMDB CSV import | Yes |
| M11 Enterprise auth | Yes (OIDC/LDAP mock locally; live IdP until configured) |
| M12 Banner package + public API | Yes |
| M13 Demo data, tests, deploy docs | Yes |

Unsupported capabilities: [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and in-app **About**.

## Auth safety

- `AUTH_MODE=local_dev` is **refused** when `ENVIRONMENT` is `staging` or `production` unless `ALLOW_LOCAL_AUTH=true` (audited break-glass).
- Deployed environments must set `AUTH_MODE=oidc` or `ldap`.

## API docs

With the API running: http://localhost:8000/docs
