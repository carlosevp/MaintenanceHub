# MaintenanceHub implementation audit

**Branch audited:** reconciled tip `cursor/pr5-pr6-reconcile-0ed4` (PR #6 audit baseline + PR #5 M3b)  
**Sources of truth:** Project store product-brief / PRD / ADRs / data-model / api-contracts / milestone-plan; repo `docs/LIMITATIONS.md`; actual source (not class existence alone).  
**Date:** 2026-11-04

## Executive summary

MaintenanceHub delivers a working **communication** stack for planned maintenance and manual outages (catalog → schedule → dashboard/calendar → subscriptions/SMTP/bridge → ICS → SN poll/CSV APIs → banner → **M3b recurrence**). It is **not** a monitoring product.

PR #6 audit security/integrity fixes are preserved (application-scoped grants, public banner without browser secrets, approval-confirm outbox, OpenShift `API_UPSTREAM`, weak JWT / `create_all` guards, Compose+Postgres, Makefile lint). PR #5 adds bounded RRULE expansion, occurrence identity, series edit scopes, and phase distinctions (approved ≠ outage). Remaining gaps are mostly **admin UI**, **digests**, and **live IdP**.

---

## Requirement map

Legend: **F** = fully functional · **P** = partially functional · **S** = stubbed · **M** = missing

| Requirement (brief/PRD) | Status | Implementation | Tests | UI |
|-------------------------|--------|----------------|-------|-----|
| Catalog apps/envs/owners/tags/deps | **P** | API `catalog.py`; models; seed | `test_authz_catalog.py` | Catalog pages; no owner/tag admin UX depth |
| One-time maintenance lifecycle | **F** | `domain/lifecycle.py`, `domain/events.py`, `api/events.py` | `test_lifecycle.py`, `test_events_lifecycle.py` | Create + detail transitions (subset) |
| Per-occurrence lifecycle | **F** | Sparse `occurrence_records`; `domain/occurrences.py`; occurrence APIs; dashboard/calendar overlay | `test_occurrence_lifecycle.py` | Event detail per-occ Start/Extend/Verify/Complete/Cancel + history |
| Recurrence (M3b) | **F** | `domain/recurrence.py` expansion; series scopes; ICS RECURRENCE-ID; exception reconciliation on RRULE change | `test_recurrence_*`, `test_m3b_harden`, reconcile E2E, occurrence tests | RecurrenceEditor + calendar + series edit reconcile |
| Approved vs confirmed | **F** | `ApprovalState`; banner/notify respect confirmed | Banner + cross-module | Create + confirm via PATCH |
| Manual outages | **F** | `EventKind.manual_outage` | Lifecycle API | Create + dashboard badges |
| Dashboard current/upcoming/recent/outages | **F** | `api/dashboard.py` | Indirect via seed | `DashboardPage` |
| Calendar day/week/month | **F** | Shared bounded expansion with dashboard/ICS | M3b + reconcile E2E I | `CalendarPage` |
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
| Low | Recurrence `all` edit may orphan exceptions (documented) |
| Medium | Digest notification worker |
| Medium | SN events without ExternalCiLink stay impact-less |
| Medium | Fine-grained grants on all catalog mutations / directory-group grants |
| Low | UI missing reschedule / full transition matrix / delivery history views |
| Low | Postgres concurrency covered in `tests/worker/test_postgres_concurrency.py` (requires TEST_POSTGRES_URL) |

---

## OpenShift / Compose / Makefile

| Area | Finding | Action |
|------|---------|--------|
| Web→API | `API_UPSTREAM` env + entrypoint sed into nginx template | Fixed |
| Migrations | Compose `migrate` service runs Alembic before API | Added |
| Persistence | Postgres volume in Compose; `compose-down` preserves volumes; `compose-reset` destroys | Fixed |
| Security context | non-root 10001 | Present |
| Makefile | Lightweight SQLite targets preserved; lint fails on errors | Fixed |

---

## Functional demo checklist (executed on reconcile tip)

| Check | Command / action | Result |
|-------|------------------|--------|
| Full pytest (+ Postgres J) | `TEST_POSTGRES_URL=postgresql+psycopg://mh:mh@127.0.0.1:5432/mh_test pytest tests -q` | **85 passed** |
| Banner package | `cd packages/banner && npm test && npm run build` | **2 passed**, build OK |
| Web vitest + production build | `cd apps/web && npm test && npm run build` | **2 passed**, build OK |
| Lint | `make lint` | **All checks passed** |
| E2E A–I | `tests/api/test_reconcile_e2e.py` | Pass |
| E2E J Postgres concurrency | `tests/worker/test_postgres_concurrency.py` | Pass |

Local: `make install && make migrate && make api` / `make worker` / `make web` → `publisher@demo.example.com` / `password123`.  
Compose: `make compose-up` → http://localhost:8080 (`compose-down` keeps volumes).

---

## Category rollup

| Category | Count (approx.) |
|----------|-----------------|
| Fully functional | Lifecycle, M3b recurrence, dashboard/calendar/ICS, subscriptions/SMTP/bridge, banner, fail-closed auth, grants on writes, seed |
| Partially functional | SN/CSV (API-only UX), enterprise live IdP, grants breadth, OpenShift ops polish |
| Stubbed | Digests, SN push |
| Missing / non-goal | Monitoring, Teams APIs, admin UI surfaces, native mobile |
