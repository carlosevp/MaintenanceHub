# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.”

## Current wave (through M11)

| Item | Status |
|------|--------|
| **M3b Recurrence** | Schema + ICS RRULE emit; in-app calendar occurrence expansion / DST fixtures incomplete. |
| **M5–M8** | Jobs, subscriptions/SMTP/log, email bridge, ICS — implemented (digests schema-only). |
| **M9 ServiceNow poll** | **Implemented**: poll adapter (null / fixture / HTTP), upsert by sys_id, cancel mapping, unmatched queue (link/create/ignore), dry-run, push interface stub only. Live HTTP requires env secrets + `SERVICENOW_ENABLED=true` + `SERVICENOW_USE_FIXTURE=false`. |
| **M10 CMDB CSV** | **Implemented**: upload/preview/commit/history for CIs + relationship CSV; preserves `origin=manual` unless `overwrite_manual_dependencies`. |
| **M11 Enterprise auth** | **Implemented**: fail-closed local_dev; OIDC + LDAP provider abstraction with **mock IdP/LDAP for local/tests**; live OIDC token exchange / LDAP bind raise until fully configured. Group→role mappings, service credentials, audit log, scoped banner read. |
| **Banner package** | Stub under `packages/banner` (full package polish → M12). Public banner API exists for service creds. |
| **OpenShift manifests** | Minimal placeholders under `deploy/openshift/`. |
| **Application-scoped grants enforcement** | Grants table + mappings exist; fine-grained per-app write enforcement still limited. |

## Enabling ServiceNow locally (fixtures)

```bash
export SERVICENOW_ENABLED=true
export SERVICENOW_USE_FIXTURE=true
export SERVICENOW_FIXTURE_PATH=fixtures/servicenow_changes.json
# Dry-run (no DB writes):
curl -X POST .../api/v1/admin/servicenow/poll-now -d '{"dry_run":true}'
# Apply fixture:
curl -X POST .../api/v1/admin/servicenow/poll-now -d '{"fixture_records":[...]}'
```

With `SERVICENOW_ENABLED=false`, the null adapter makes **no HTTP calls**.

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (**Teams via email bridge only**)
- ServiceNow push/webhooks (interface stub only)
- `/healthz` and `/readyz` are **platform probes for MaintenanceHub pods only**

## SQLite local profile

Run **one worker** only. Multi-replica lease safety requires Postgres.
