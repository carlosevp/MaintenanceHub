# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.” Also linked from the in-app **About** page.

## Through M3b / M13

| Item | Status |
|------|--------|
| **M0–M4** | Implemented (catalog, one-time scheduling, dashboard/calendar). |
| **M3b Recurrence** | **Implemented** (see [recurrence.md](./recurrence.md)): RRULE weekly/monthly/daily/custom; multi-weekday; interval; until/count; IANA TZ + DST expansion; exceptions; series scopes `this` / `this_and_future` / `all`; calendar + dashboard + ICS share expansion; stable occurrence ids; per-occurrence reminder idempotency. Occurrences expanded for bounded windows only. |
| **M5–M8** | Jobs, subscriptions/SMTP/log, Teams-via-email-bridge, ICS — implemented. Digest worker is schema-only. |
| **M9 ServiceNow poll** | Implemented (null / fixture / HTTP). Live HTTP needs secrets. Push/webhooks = interface stub only. |
| **M10 CMDB CSV** | Implemented; preserves `origin=manual` unless overwrite flag. |
| **M11 Enterprise auth** | Fail-closed `local_dev`; OIDC/LDAP mock for local/tests. Live IdP until configured. |
| **M12 Banner** | Implemented. |
| **M13 Demo / deploy** | Seed + OpenShift docs/manifests. |
| **Application-scoped grants** | Fine-grained per-app write enforcement still limited. |
| **Native mobile / Redis / RabbitMQ** | Out of scope. |

## Recurrence caveats (known)

- **`all` series edit + exceptions:** Exceptions remain keyed by `original_starts_at`. Changing DTSTART/RRULE can leave exceptions that no longer match generated slots (kept for audit; clear manually if obsolete).
- **`this_and_future` split:** Historical data stays on the truncated master; the new series gets a new event id (subscriptions targeting the old event id are not auto-rewired — app-targeted subscriptions still match via impacts).
- **Dashboard “current”:** Only human-published **executing** statuses in-window. A confirmed series still in `scheduled` that overlaps now is **not** treated as executing or as an outage. Approved windows never appear as current/outage and do not send reminders.
- **Per-occurrence lifecycle:** Recurring masters typically stay `scheduled` for the series; individual occurrence execution is not a separate DB row (communicate via exceptions / series transitions).

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (**Teams via email bridge only**)
- ServiceNow push/webhooks (poll adapter only)
- `/healthz` / `/readyz` reflecting catalog application health — MaintenanceHub pod probes only

## SQLite local profile

Run **one API** and **one worker** only. Multi-replica lease safety requires Postgres.
