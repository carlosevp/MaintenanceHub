# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.” Also linked from the in-app **About** page. See [IMPLEMENTATION_AUDIT.md](./IMPLEMENTATION_AUDIT.md) for the full requirement map.

## Through M3b / M13 (honest status)

| Item | Status |
|------|--------|
| **M0–M4** | **Functional** via API + primary UI (catalog, one-time scheduling, dashboard/calendar). |
| **M3b Recurrence** | **Implemented** (see [recurrence.md](./recurrence.md)): RRULE weekly/monthly/daily/custom; multi-weekday; interval; until/count; IANA TZ + DST expansion; exceptions; series scopes `this` / `this_and_future` / `all`; calendar + dashboard + ICS share expansion; stable occurrence ids; per-occurrence reminder idempotency. Occurrences expanded for bounded windows only. |
| **M5–M8** | **Functional** jobs, SMTP/log, Teams-via-email-bridge, ICS. **Digest worker = schema-only.** Support-group subscription targets do not match. |
| **M9 ServiceNow poll** | **Functional** null/fixture/HTTP poll, upsert by sys_id, cancel, unmatched resolve + **Admin UI** (status without secrets, dry-run, poll-now, unmatched). Impacts attached **only when** `ExternalCiLink` maps `cmdb_ci` → application. Push/webhooks = interface stub. |
| **M10 CMDB CSV** | **Functional** preview/commit/history via admin API + **Admin UI**. Partial CSV never deletes absent relationships. |
| **M11 Enterprise auth** | Fail-closed `local_dev`; OIDC/LDAP **mock** for local/tests. Live IdP exchange/bind need real config. Admin surfaces prepare for AD; **no fake production AD login**. |
| **M12 Banner** | **Functional** package + `/api/v1/public/banner`. Public DTO is **unauthenticated** (browser-safe). Do **not** embed `client_secret` in frontends. |
| **M13 Demo / deploy** | Seed + Compose (Postgres) + OpenShift manifests. Web nginx uses `API_UPSTREAM`. Production must run Alembic (no `create_all`). |
| **Application-scoped grants** | **Enforced** on event mutations and application updates. **Admin UI** for grant CRUD + group→role maps. Directory-group → ApplicationGrant auto-provision still limited. |
| **M14 Impact analysis** | **Implemented + hardened**: dependency reverse traversal, publisher-scoped preview, confirm with revision tokens, etc. Advisory only; graph quality depends on CMDB/manual edges. |
| **M15 Admin workspace** | **Implemented**: `/admin` Overview, Apps/Deps, SN/CMDB, Notifications, Users/Permissions, Jobs/Delivery, Audit. API authz required. Secrets are env/OpenShift only (status/redaction; no secret editor). See [administration.md](./administration.md). |
| **M16 Consumer & publisher UX** | **Implemented**: My Applications homepage; calendar day/week/month/agenda + filters; four-step publisher wizard (Details→Impact→Audience→Review) with drafts/templates/Quick Publish; subscription app/env/event targets + multi-reminders; clearer email/bridge templates; authenticated shareable status URLs (`/status/apps/...`, `/status/events/...`, `/status/scheduled/...`). |
| **Native mobile / Redis / RabbitMQ** | Out of scope. |

## Recurrence / occurrence caveats (known)

- **`all` series edit + exceptions:** Before RRULE/DTSTART changes, the API runs **exception reconciliation**. Historical executed occurrence records and notification audit are never discarded. Incompatible *future* exceptions require an explicit policy (`exception_reconcile=drop_incompatible_future` or `drop_exception_originals`) — silent orphaning is rejected.
- **`this_and_future` split:** Historical data stays on the truncated master; the new series gets a new event id (subscriptions targeting the old event id are not auto-rewired — app-targeted subscriptions still match via impacts).
- **Dashboard “current”:** Only human-published **executing** statuses in-window (per occurrence when a sparse record exists). A confirmed series still in master `scheduled` that overlaps now is **not** treated as executing unless that occurrence was started. Approved windows never appear as current/outage and do not send reminders.
- **Per-occurrence lifecycle:** Sparse `occurrence_records` persist only for overrides/state/audit (no unbounded materialization). Recurring masters typically stay `scheduled`; Start/Extend/Verifying/Complete/Cancel are per-occurrence APIs. Clock time never auto-completes.
- **Occurrence notification targeting:** Effective impacts = occurrence override when `impacts_overridden` (including an explicit empty set); otherwise series defaults. `app_environment` subscriptions match **(application, environment) pairs** on the same impact row — not independent app/env ID sets. Event-level subscriptions match once (deduped). Impact changes reconcile queued reminders; sent delivery history is immutable. Lifecycle still requires grants on every *effective* impacted application (proposing a downstream app without a grant is allowed on patch, but lifecycle of that occurrence then needs grants on all effective apps).
- **M14 confirm vs lifecycle grants:** Impact confirm requires grants on **seed** applications only (infra-only events: creator or admin). Including downstream apps for notification reach does not assert those apps unavailable. Manual adds require grants on the added apps. After confirm, occurrence lifecycle of a multi-app effective set may still need grants on all effective apps.
- **M14 preview staleness / selection:** Revision token covers seeds, window, event/occ identity, exclusions, manuals, proposed set, and dependency fingerprint. Confirm rejects (409) stale tokens and unreviewed selection changes (`include_downstream` must match last previewed proposed set).
- **M14 destination privacy:** Audience **counts** are always returned to authorized publishers; raw email/Teams destinations are omitted when seed-app grants are missing (viewers cannot call preview at all).
- **Support-group subscription targets:** Still non-matching (deferred).
- **M16 status pages:** Authenticated viewers only (same session as the app). Not anonymous public AD status. Share URLs omit internal notes/timeline.
- **M16 ICS:** Feed refresh is client poll interval only — not push-realtime.
- **M16 publisher reminders:** Wizard reminder offsets document publisher expectation; actual reminder delivery is owned by consumer subscriptions.
- **M16 drafts:** Local browser draft only (not server-persisted drafts).

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
