# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.” Also linked from the in-app **About** page. See [IMPLEMENTATION_AUDIT.md](./IMPLEMENTATION_AUDIT.md) for the full requirement map.

## Through M3b / M13 (honest status)

| Item | Status |
|------|--------|
| **M0–M4** | **Functional** via API + primary UI (catalog, one-time scheduling, dashboard/calendar). |
| **M3b Recurrence** | **Implemented** (see [recurrence.md](./recurrence.md)): RRULE weekly/monthly/daily/custom; multi-weekday; interval; until/count; IANA TZ + DST expansion; exceptions; series scopes `this` / `this_and_future` / `all`; calendar + dashboard + ICS share expansion; stable occurrence ids; per-occurrence reminder idempotency. Occurrences expanded for bounded windows only. |
| **M5–M8** | **Functional** jobs, SMTP/log, Teams-via-email-bridge, ICS. **Digest worker = schema-only.** Support-group subscription targets do not match. |
| **M9 ServiceNow poll** | **Functional** null/fixture/HTTP poll, upsert by sys_id, cancel, unmatched resolve. Impacts attached **only when** `ExternalCiLink` maps `cmdb_ci` → application. Push/webhooks = interface stub. **No admin UI** (API only). |
| **M10 CMDB CSV** | **Functional** preview/commit/history via **admin API only** — no web UI. |
| **M11 Enterprise auth** | Fail-closed `local_dev`; OIDC/LDAP **mock** for local/tests. Live IdP exchange/bind need real config. |
| **M12 Banner** | **Functional** package + `/api/v1/public/banner`. Public DTO is **unauthenticated** (browser-safe). Do **not** embed `client_secret` in frontends. |
| **M13 Demo / deploy** | Seed + Compose (Postgres) + OpenShift manifests. Web nginx uses `API_UPSTREAM`. Production must run Alembic (no `create_all`). |
| **Application-scoped grants** | **Enforced** on event mutations (incl. series/occurrence edits) and application updates. Creator auto-granted. Directory-group grants and fine-grained catalog CRUD still limited. |
| **M14 Impact analysis** | **Implemented**: dependency reverse traversal, preview (audience/conflicts/revision token), confirm+outbox, publish-flow UX, Oracle NON-PROD seed. **Advisory only** — conflicts never block publish; no auto health; dependency graph quality depends on CMDB/manual edges (absent ≠ none). Infra/service catalog admin UX still thin (list API only). |
| **Admin UX** | SN unmatched, CSV import, service credentials, audit, jobs, role mappings — **API-only** (no in-app admin screens). |
| **Native mobile / Redis / RabbitMQ** | Out of scope. |

## Recurrence / occurrence caveats (known)

- **`all` series edit + exceptions:** Before RRULE/DTSTART changes, the API runs **exception reconciliation**. Historical executed occurrence records and notification audit are never discarded. Incompatible *future* exceptions require an explicit policy (`exception_reconcile=drop_incompatible_future` or `drop_exception_originals`) — silent orphaning is rejected.
- **`this_and_future` split:** Historical data stays on the truncated master; the new series gets a new event id (subscriptions targeting the old event id are not auto-rewired — app-targeted subscriptions still match via impacts).
- **Dashboard “current”:** Only human-published **executing** statuses in-window (per occurrence when a sparse record exists). A confirmed series still in master `scheduled` that overlaps now is **not** treated as executing unless that occurrence was started. Approved windows never appear as current/outage and do not send reminders.
- **Per-occurrence lifecycle:** Sparse `occurrence_records` persist only for overrides/state/audit (no unbounded materialization). Recurring masters typically stay `scheduled`; Start/Extend/Verifying/Complete/Cancel are per-occurrence APIs. Clock time never auto-completes.
- **Occurrence notification targeting:** Effective impacts = occurrence override when `impacts_overridden` (including an explicit empty set); otherwise series defaults. `app_environment` subscriptions match **(application, environment) pairs** on the same impact row — not independent app/env ID sets. Event-level subscriptions match once (deduped). Impact changes reconcile queued reminders; sent delivery history is immutable. Lifecycle still requires grants on every *effective* impacted application (proposing a downstream app without a grant is allowed on patch, but lifecycle of that occurrence then needs grants on all effective apps).
- **M14 confirm vs lifecycle grants:** Impact confirm requires grants on **seed** applications only; including downstream apps for notification reach does not assert those apps unavailable and does not require grants on them. After confirm, occurrence lifecycle of a multi-app effective set may still need grants on all effective apps.
- **M14 preview staleness:** Confirm rejects mismatched `revision_token` (409) when dependency fingerprint or event `impact_revision` changes between preview and publish.
- **Support-group subscription targets:** Still non-matching (deferred).

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (**Teams via email bridge only**)
- ServiceNow push/webhooks (poll adapter only)
- `/healthz` and `/readyz` reflecting catalog application health — they are **platform probes for MaintenanceHub pods only**

## SQLite local profile

Use Makefile targets (`make api` / `make worker` / `make web`). Run **one API** and **one worker** only. Multi-replica lease safety requires Postgres (`docker compose up` / `make compose-up`). `make compose-down` preserves volumes; use `make compose-reset` to destroy them.

## Enabling ServiceNow locally (fixtures)

```bash
export SERVICENOW_ENABLED=true
export SERVICENOW_USE_FIXTURE=true
export SERVICENOW_FIXTURE_PATH=fixtures/servicenow_changes.json
curl -X POST .../api/v1/admin/servicenow/poll-now -d '{"dry_run":true}'
```

With `SERVICENOW_ENABLED=false`, the null adapter makes **no HTTP calls**.
