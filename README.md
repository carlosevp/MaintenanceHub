# MaintenanceHub

Internal **Maintenance & Outage Communication Platform**.

This is **not** a monitoring product. Status is published by people (planned maintenance, extensions, manual outages). Platform `/healthz` and `/readyz` exist only for pod liveness/readiness.

Architecture source of truth lives in the Project store docs (PRD, ADRs, data model, API contracts, milestone plan). This repository implements milestones **M0 → M18** (catalog through UX profiles, and public/internal banner embeds). See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for remaining gaps.

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

All demo titles are prefixed with `[DEMO]`. Seed includes apps (`payments-gateway`, `hr-portal`, `inventory-svc`), tags, a manual dependency, favorites, current/upcoming/recent events, a manual outage, and a **weekly recurring** Payments window (with one skipped occurrence) plus a monthly **approved_window** series.

### Banner package (M18)

```bash
cd packages/banner && npm install && npm test && npm run build
```

- Package README: [packages/banner/README.md](packages/banner/README.md)
- Developer guide (JS / TS / JSON, local, OpenShift, CORS/CSP): [docs/banner-developer-guide.md](docs/banner-developer-guide.md)
- API contract: [docs/banner-api.md](docs/banner-api.md)
- In-app **Embed banner**: `/banner-demo` (Claims INT demo story)

**Browser embeds** must use the configured **HTTPS** corporate base (`PUBLIC_BASE_URL` / Embed screen). Do **not** put OpenShift service DNS (`maintenancehub-api`) or `client_secret` in browser snippets. Optional service JWTs need scope `banner:read` and belong on a BFF only.

```bash
# Public DTO — no credentials required
curl -s "http://127.0.0.1:8000/api/v1/public/banner?application_key=claims&environment_key=INT"

# In-cluster shape (BFF / OpenShift only)
curl -s "http://127.0.0.1:8000/api/v1/internal/banner?application_key=claims&environment_key=INT"
```

`embed.js` is hand-synced with the TypeScript package — change both when editing banner UX (see developer guide).

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). **`main` is the default base.** Open one focused PR per change — do not stack long feature branches.

## Milestone acceptance

| Milestone | Met? |
|-----------|------|
| M0–M4 Bootstrap, catalog, scheduling, dashboard | Yes |
| M3b Recurrence expansion | Yes (RRULE + exceptions + calendar/ICS/reminders; bounded expand) |
| M5–M8 Jobs, notify, bridge, ICS | Yes |
| M9 ServiceNow poll | Yes (fixture/null by default) |
| M10 CMDB CSV import | Yes |
| M11 Enterprise auth | Yes (OIDC/LDAP mock locally; live IdP until configured) |
| M12 Banner package + public API | Yes |
| M13 Demo data, tests, deploy docs | Yes |
| Occurrence-level lifecycle (sparse records) | Yes |
| M14 Impact analysis & notification preview | Yes |
| M15 Enterprise administration workspace | Yes |
| M16 Consumer & publisher experience | Yes |
| M17 UX redesign + experience profiles | Yes |

Unsupported capabilities: [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and in-app **About**.

### Zero-config demo (M17)

Synthetic data, local_dev auth, and **captured notifications** under `data/notification-capture/` (SMTP off). No ServiceNow, SMTP relay, or AD required.

```bash
make demo              # Essentials (default) — Claims INT story available
make demo-essentials   # same as make demo
make demo-team         # Team — Weekly Payments + Oracle NON-PROD impact stories
make demo-enterprise   # Enterprise — full admin / SN / CSV surfaces
make demo-stop
```

Three **presentation-only** demo stories appear in the Overview “Demo stories” selector. Selecting a story navigates to seeded data; it **cannot** unlock APIs disabled by `EXPERIENCE_PROFILE`. Unknown profiles fail closed (never silent Enterprise).

Prints URL + demo credentials. Refuses to run when `ENVIRONMENT` is staging/production.

Screenshots: [docs/artifacts/m17/](docs/artifacts/m17/).

## Auth safety

- `AUTH_MODE=local_dev` is **refused** when `ENVIRONMENT` is `staging` or `production` unless `ALLOW_LOCAL_AUTH=true` (audited break-glass).
- Deployed environments must set `AUTH_MODE=oidc` or `ldap`.

## API docs

With the API running: http://localhost:8000/docs
