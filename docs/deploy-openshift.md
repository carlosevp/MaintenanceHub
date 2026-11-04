# OpenShift deployment

MaintenanceHub runs as three Deployments: **web**, **api**, **worker**, plus managed **Postgres**. No Redis/RabbitMQ.

## Prerequisites

- OpenShift project / namespace
- Postgres 14+ reachable from the cluster
- Container images built from repo Dockerfiles (non-root UID `10001`)
- IdP configured if `AUTH_MODE=oidc` or `ldap` (do **not** use `local_dev` in production)

## Secrets & config

1. Create secrets (DB URL, JWT, SMTP, OIDC/LDAP, optional ServiceNow):

```bash
oc create secret generic maintenancehub-secrets \
  --from-literal=DATABASE_URL='postgresql+psycopg://mh:SECRET@postgres:5432/maintenancehub' \
  --from-literal=JWT_SECRET='long-random-string' \
  --from-literal=OIDC_CLIENT_SECRET='…'
```

2. Create non-secret config from `deploy/openshift/config.env.example`:

```bash
oc create configmap maintenancehub-config --from-env-file=deploy/openshift/config.env.example
```

Required production settings:

| Key | Value |
|-----|--------|
| `ENVIRONMENT` | `production` |
| `AUTH_MODE` | `oidc` or `ldap` |
| `ALLOW_LOCAL_AUTH` | `false` |
| `SEED_DEMO_DATA` | `false` |
| `DATABASE_URL` | Postgres URL (secret) |

`AUTH_MODE=local_dev` with `ENVIRONMENT=production` **fails closed** at startup unless break-glass `ALLOW_LOCAL_AUTH=true`.

## Apply manifests

```bash
# Build & push images to the internal registry, then:
oc apply -k deploy/openshift/
# or individually:
oc apply -f deploy/openshift/api.yaml
oc apply -f deploy/openshift/worker.yaml
oc apply -f deploy/openshift/web.yaml
```

Point Routes at your DNS. The web image entrypoint substitutes `API_UPSTREAM` (default `http://api:8000`; OpenShift manifest sets `http://maintenancehub-api:8000`) into the nginx config so `/api/` reaches the API Service.

## Replicas

| Component | Suggested | Notes |
|-----------|-----------|--------|
| api | ≥2 | Stateless |
| worker | ≥2 | Safe with Postgres `SKIP LOCKED` / lease reclaim |
| web | ≥2 | Static assets |
| SQLite | **api=1, worker=1** | Local/dev only — not for OpenShift multi-replica |

## Migrations

Run Alembic once before traffic (Job or init):

```bash
DATABASE_URL=postgresql+psycopg://… alembic -c db/alembic.ini upgrade head
```

## Health probes

- `/healthz` — liveness (process up)
- `/readyz` — readiness (DB reachable)

These are **MaintenanceHub pod probes only**, not application uptime monitoring.

## Banner embeds

Create a service credential with scope `banner:read`, mint a token via `POST /api/v1/auth/service/token`, and point `@maintenancehub/banner` at the public API base URL. See `packages/banner/README.md`.
