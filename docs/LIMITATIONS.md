# Limitations & incomplete capabilities (M0–M4 slice)

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.”

## Incomplete in this PR

| Item | Status |
|------|--------|
| **M3b Recurrence** | Schema (`recurrence_rules`, `recurrence_exceptions`) exists. Create may flag `is_recurring` if a recurrence object is sent, but **RRULE expansion, exceptions, and DST fixtures are not implemented**. Calendar returns master events only. |
| **M5 Durable jobs** | Outbox + `jobs` rows are written on event transitions. Worker process is a **stub** that logs queue depth and does not claim/lease/execute jobs. |
| **Subscriptions / SMTP / Power Automate bridge** | Not implemented (M6–M7). Feature flags default off. |
| **ICS calendar feeds** | Not implemented (M8). |
| **ServiceNow poll / CMDB CSV** | Not implemented (M9–M10). Adapters disabled. |
| **Enterprise OIDC/LDAP** | Provider hooks via `AUTH_MODE`; only `local_dev` login works. Fail-closed startup guard is implemented. |
| **Banner package** | Stub package under `packages/banner` (M12). |
| **OpenShift manifests** | Minimal placeholders under `deploy/openshift/`. |
| **Application-scoped grants enforcement** | Grants table exists; publishers currently write globally in this slice (full grant checks → M11). |

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (use email bridge later)
- `/healthz` and `/readyz` are **platform probes for MaintenanceHub pods only**

## SQLite local profile

Run **one worker** only. Lease/`SKIP LOCKED` multi-replica behavior requires Postgres (M5).
