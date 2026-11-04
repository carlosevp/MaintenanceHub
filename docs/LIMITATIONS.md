# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.” Also linked from the in-app **About** page.

## Through M13

| Item | Status |
|------|--------|
| **M0–M4** | Implemented (catalog, one-time scheduling, dashboard/calendar). |
| **M3b Recurrence** | **Deferred / partial**: schema + ICS RRULE emit exist; in-app calendar occurrence expansion and DST fixture suite are **not** complete. |
| **M5–M8** | Jobs, subscriptions/SMTP/log, Teams-via-email-bridge, ICS — implemented. Digest worker is schema-only. |
| **M9 ServiceNow poll** | Implemented (null / fixture / HTTP). Live HTTP needs secrets + `SERVICENOW_ENABLED=true` + `SERVICENOW_USE_FIXTURE=false`. Push/webhooks = interface stub only. |
| **M10 CMDB CSV** | Implemented; preserves `origin=manual` unless overwrite flag. |
| **M11 Enterprise auth** | Fail-closed `local_dev`; OIDC/LDAP providers with **mock** for local/tests. Live token exchange / LDAP bind require real IdP config. |
| **M12 Banner** | **Implemented**: `@maintenancehub/banner` package, `/api/v1/public/banner`, demo page, service-cred `banner:read`. |
| **M13 Demo / deploy** | Labeled seed data; OpenShift manifests under `deploy/openshift/`; see `docs/deploy-openshift.md`. |
| **Application-scoped grants** | Grants table + mappings exist; fine-grained per-app write enforcement still limited. |
| **Native mobile / Redis / RabbitMQ** | Out of scope. |

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (**Teams via email bridge only**)
- ServiceNow push/webhooks (poll adapter only)
- `/healthz` and `/readyz` reflecting catalog application health — they are **platform probes for MaintenanceHub pods only**

## SQLite local profile

Run **one API** and **one worker** only. Multi-replica lease safety requires Postgres.

## Enabling ServiceNow locally (fixtures)

```bash
export SERVICENOW_ENABLED=true
export SERVICENOW_USE_FIXTURE=true
export SERVICENOW_FIXTURE_PATH=fixtures/servicenow_changes.json
curl -X POST .../api/v1/admin/servicenow/poll-now -d '{"dry_run":true}'
```

With `SERVICENOW_ENABLED=false`, the null adapter makes **no HTTP calls**.
