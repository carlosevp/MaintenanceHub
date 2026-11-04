# MaintenanceHub implementation audit

**Branch audited:** `cursor/m12-m13-banner-deploy-0ed4` tip (+ this audit PR fixes)  
**Sources of truth:** Project store product-brief / PRD / ADRs / data-model / api-contracts / milestone-plan; repo `docs/LIMITATIONS.md`; actual source (not class existence alone).  
**Date:** 2026-11-04

## Executive summary

MaintenanceHub delivers a working **communication** stack for planned maintenance and manual outages (catalog → schedule → dashboard/calendar → subscriptions/SMTP/bridge → ICS → SN poll/CSV APIs → banner). It is **not** a monitoring product.

Critical integrity/security gaps found on the stacked tip were **fixed in this audit PR** (application-scoped grant enforcement, public banner without browser secrets, approval-confirm outbox, reminder reschedule refresh, SN CI→impact linking, OpenShift `API_UPSTREAM`, weak JWT / `create_all` guards, Compose+Postgres, Makefile lint). Remaining gaps are mostly **admin UI**, **M3b recurrence expansion**, **digests**, and **live IdP** — documented below, not disguised as finished.

---

## Requirement map

Legend: **F** = fully functional · **P** = partially functional · **S** = stubbed · **M** = missing

| Requirement (brief/PRD) | Status | Implementation | Tests | UI |
|-------------------------|--------|----------------|-------|-----|
| Catalog apps/envs/owners/tags/deps | **P** | API `catalog.py`; models; seed | `test_authz_catalog.py` | Catalog pages; no owner/tag admin UX depth |
| One-time maintenance lifecycle | **F** | `domain/lifecycle.py`, `domain/events.py`, `api/events.py` | `test_lifecycle.py`, `test_events_lifecycle.py` | Create + detail transitions (subset) |
| Recurrence (M3b) | **P/S** | Flag + ICS RRULE emit; no expansion | Limited | None for RRULE editor |
| Approved vs confirmed | **F** | `ApprovalState`; banner/notify respect confirmed | Banner + cross-module | Create + confirm via PATCH |
| Manual outages | **F** | `EventKind.manual_outage` | Lifecycle API | Create + dashboard badges |
| Dashboard current/upcoming/recent/outages | **F** | `api/dashboard.py` | Indirect via seed | `DashboardPage` |
| Calendar day/week/month | **P** | API range + web calendar | Partial | `CalendarPage` (no occurrence expansion) |
| Favorites | **F** | Model + API + seed | Catalog/authz | Dashboard |
| Subscriptions + reminders | **F** | `subscriptions` + worker | Dedupe + cross-module | `SubscriptionsPage` |
| SMTP / log sink | **F** | `adapters/smtp.py` | Bridge/ICS tests | Test-send on subscriptions |
| Teams via email bridge | **F** | Bridge adapter + subject template | `test_ics_and_bridge.py` | Destination type in UI |
| Digests | **S** | `digest_mode` column only | None | None |
| ICS feeds + revocable tokens | **F** | `calendar_tokens` + ICS builder | `test_ics_and_bridge.py` | Token create on subscriptions |
| ServiceNow poll | **P** | Adapters + `servicenow_sync` | Idempotent/cancel tests | **API only** |
| SN push/webhooks | **S** | `StubPushChangeAdapter` | None | N/A |
| CMDB CSV import | **P** | `csv_import` domain + admin API | `test_csv_import.py` | **API only** |
| Local-dev auth + seeded roles | **F** | Auth + seed | Many | Login |
| OIDC/LDAP enterprise | **P** | Providers + mock; live bind deferred | `test_enterprise_auth.py` | Login modes partial |
| Fail-closed local_dev in prod | **F** | Settings validator | `test_fail_closed_auth.py` | N/A |
| Application-scoped permissions | **P→F*** | `ApplicationGrant` + `domain/authz.py` on event/app writes | `test_app_grants.py` | No grant admin UI |
| Service credentials | **F** | Admin API + token endpoint | Enterprise + banner tests | **API only** |
| Audit log | **F** | Admin audit list | Enterprise tests | **API only** |
| Public banner API + JS package | **F** | `api/banner.py`, `packages/banner` | Banner + sanitize tests | `/banner-demo` |
| OpenAPI | **F** | FastAPI `/docs` | — | — |
| Non-root containers / OpenShift | **P→F*** | Dockerfiles UID 10001; manifests; `API_UPSTREAM` | Manual | — |
| Demo data | **F** | `seed.py` `[DEMO]` | Seed smoke | Dashboard |
| Monitoring / Teams APIs | **M** (non-goal) | Absent by design | — | About/LIMITATIONS |

\*Improved in this audit PR.

---

## Deep-review notes

### Lifecycle
Working state machine with timeline + transactional outbox. UI covers a subset of transitions (no reschedule form, limited extend paths). Confirming `approval_state` now writes timeline + `event.confirmed` outbox and schedules reminders.

### Notifications
Outbox → lease jobs → SMTP/log/bridge with delivery idempotency. Reminder jobs refresh `run_at` on reschedule. Digests and support-group targets are stubs.

### CSV / ServiceNow
API-complete for poll/import/unmatched resolve. No admin UI. SN events attach impacts when `ExternalCiLink` maps CI sys_id; otherwise events remain impact-less (subscriptions won’t match apps).

### ICS
Token create/revoke + feed generation work; empty without favorites/subscriptions as designed.

### Authorization
Global RBAC was always enforced. **Application grants are now enforced** on event create/mutate and application PATCH; app creators receive a grant. Platform admin bypasses. Group→grant mapping and broad catalog grant coverage remain partial.

### Banner auth (browser)
`/api/v1/public/banner` returns the minimal public DTO **without requiring credentials**, so embeds need not ship long-lived secrets. Service credentials with `banner:read` remain valid for server-side callers. Package README forbids `client_secret` in frontends.

---

## Prioritized defects / missing requirements

### Fixed in this PR (were critical)

1. **ApplicationGrant unenforced** — any publisher could mutate any app’s events.  
2. **Banner design pushed long-lived service tokens into browsers** — public unauthenticated read for minimal DTO + docs.  
3. **Confirming SN/`approved_window` via PATCH skipped outbox/reminders.**  
4. **Reminder jobs kept stale `run_at` after reschedule.**  
5. **OpenShift/web nginx hardcoded `http://api:8000`** — ignored `API_UPSTREAM`.  
6. **Weak default `JWT_SECRET` allowed in production settings.**  
7. **`create_all` ran in all environments** — Alembic drift risk.  
8. **Compose Postgres profile unused by api/worker** — now integrated Compose stack.  
9. **`make lint || true` swallowed failures.**  
10. **`update_application` returned via undefined `_`** (latent NameError after grant edit).

### Remaining (not fake-fixed)

| Priority | Item |
|----------|------|
| High | No admin UI for SN unmatched, CSV, service creds, audit, jobs, role maps |
| High | Live OIDC/LDAP not usable until real IdP configured |
| Medium | M3b calendar occurrence expansion / DST fixtures |
| Medium | Digest notification worker |
| Medium | SN events without ExternalCiLink stay impact-less |
| Medium | Fine-grained grants on all catalog mutations / directory-group grants |
| Low | UI missing reschedule / full transition matrix / delivery history views |
| Low | Postgres multi-worker claim not exercised in CI |

---

## OpenShift / Compose / Makefile

| Area | Finding | Action |
|------|---------|--------|
| Web→API | `API_UPSTREAM` env + entrypoint sed into nginx template | Fixed |
| Migrations | Compose `migrate` service runs Alembic before API | Added |
| Persistence | Postgres volume in Compose; OpenShift still expects external Postgres | Documented |
| Security context | non-root 10001 | Present |
| Makefile | Lightweight SQLite targets preserved; `compose-up` added; lint fails on errors | Fixed |

---

## Functional demo checklist (executed)

| Check | Command / action | Result |
|-------|------------------|--------|
| Unit/API/migration pytest | `PYTHONPATH=apps/api/src ENVIRONMENT=development AUTH_MODE=local_dev SEED_DEMO_DATA=false pytest tests -q` | **53 passed** |
| Banner package | `cd packages/banner && npm test && npm run build` | **2 passed**, build OK |
| Web vitest | `cd apps/web && npm test` | **2 passed** |
| Lint | `make lint` | **All checks passed** |
| Cross-module: grants | `test_app_grants.py` | Pass |
| Cross-module: confirm→notify/reminders | `test_cross_module_integrity.py` | Pass |
| Cross-module: SN CI→impact | same | Pass |
| Banner unauthenticated public DTO | `test_banner_public.py` | Pass |

Local lightweight demo (not re-run as long-lived servers in this audit): `make install && make migrate && make api` / `make worker` / `make web` → login `publisher@demo.example.com` / `password123`.

Integrated Compose: `make compose-up` → http://localhost:8080 (Postgres + migrate + api + worker + web).

---

## Category rollup

| Category | Count (approx.) |
|----------|-----------------|
| Fully functional | Core lifecycle, dashboard, subscriptions/SMTP/bridge, ICS, banner, fail-closed auth, seed |
| Partially functional | Calendar recurrence, SN/CSV (API-only UX), enterprise live IdP, grants breadth, OpenShift ops polish |
| Stubbed | Digests, SN push, M3b expansion |
| Missing / non-goal | Monitoring, Teams APIs, admin UI surfaces, native mobile |
