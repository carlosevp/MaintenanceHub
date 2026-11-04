# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.” Also linked from the in-app **About** page.

## Through M3b / M13

| Item | Status |
|------|--------|
| **M0–M4** | Implemented (catalog, one-time scheduling, dashboard/calendar). |
| **M3b Recurrence** | **Implemented**: RRULE create (weekly/monthly/daily/custom), multi-weekday, interval, until/count, IANA TZ + DST-aware expansion, exceptions (cancel/reschedule), series edit scopes (`this` / `this_and_future` / `all`), calendar + dashboard + ICS share expansion semantics, per-occurrence reminder jobs with idempotent keys. Occurrences are **not** unbounded materializations — expanded for query windows / reminder horizon only. |
| **M5–M8** | Jobs, subscriptions/SMTP/log, Teams-via-email-bridge, ICS — implemented. Digest worker is schema-only. |
| **M9 ServiceNow poll** | Implemented (null / fixture / HTTP). Live HTTP needs secrets + `SERVICENOW_ENABLED=true` + `SERVICENOW_USE_FIXTURE=false`. Push/webhooks = interface stub only. |
| **M10 CMDB CSV** | Implemented; preserves `origin=manual` unless overwrite flag. |
| **M11 Enterprise auth** | Fail-closed `local_dev`; OIDC/LDAP providers with **mock** for local/tests. Live token exchange / LDAP bind require real IdP config. |
| **M12 Banner** | Implemented: `@maintenancehub/banner`, `/api/v1/public/banner`, demo page, `banner:read`. |
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

## Recurrence notes

- Master event stores `recurrence_rules.rrule` + `recurrence_exceptions`; query APIs expand into the requested date range.
- Reminder jobs use keys `reminder:event:{id}:orig:{occurrence}:sub:{sub}:offset:{n}` (horizon = 45 days).
- `approval_state` still gates communication: `approved_window` series expand on calendar but do not enqueue reminders.
