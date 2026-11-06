# MaintenanceHub implementation audit

**Branch audited:** `cursor/m15-admin-workspace-04a5` (M15 Enterprise Administration Workspace on hardened PR #9 / `cursor/m14-impact-preview-6e6d` @ `7de5b50`)  
**Sources of truth:** Project store product-brief / PRD / ADRs / data-model / api-contracts / milestone-plan; repo `docs/LIMITATIONS.md`, `docs/administration.md`; actual source (not class existence alone).  
**Date:** 2026-11-06

## Executive summary

MaintenanceHub delivers a working **communication** stack for planned maintenance and manual outages (catalog → schedule → dashboard/calendar → subscriptions/SMTP/bridge → ICS → SN poll/CSV → banner → M3b recurrence → sparse occurrence lifecycle → M14 impact analysis → **M15 Administration workspace**). It is **not** a monitoring product.

**M15** adds a polished `/admin` UI (Overview, Apps/Dependencies, ServiceNow & CMDB, Notifications, Users/Permissions, Jobs/Delivery, Audit) gated by `platform_administrator` in the **API** (not nav alone). Minimal new APIs: overview, secrets-status (no secret values), users, grants CRUD, global dependency create/delete, infra create, delivery diagnostics; plus role-map delete, credential revoke, searchable audit filters, and safe job retry that refuses already-sent deliveries.

---

## Requirement map

Legend: **F** = fully functional · **P** = partially functional · **S** = stubbed · **M** = missing

| Requirement (brief/PRD) | Status | Implementation | Tests | UI |
|-------------------------|--------|----------------|-------|-----|
| Catalog apps/envs/owners/tags/deps | **P→F*** | API + admin dependency editor | authz + admin workspace | Catalog + `/admin/catalog` |
| One-time / occurrence / recurrence | **F** | Prior modules | Prior suites | Prior UI |
| Dashboard / calendar / favorites | **F** | Prior | Prior | Prior |
| Subscriptions + SMTP / bridge | **F** | Prior + admin notification screens | Prior + M15 | Subscriptions + `/admin/notifications` |
| Digests | **S** | Schema only | — | — |
| ICS feeds | **F** | Prior | Prior | Subscriptions |
| ServiceNow poll | **P→F*** | Adapters + admin dashboard | Prior + M15 | `/admin/servicenow` |
| SN push/webhooks | **S** | Stub | — | N/A |
| CMDB CSV import | **P→F*** | Domain + admin UI upload/preview/commit/history | `test_csv_import` + M15 | `/admin/servicenow` |
| Local-dev auth + seeded roles | **F** | Auth + seed (+ M15 group maps) | Many | Login |
| OIDC/LDAP enterprise | **P** | Providers + mock; live bind deferred | enterprise | Surfaces prepared; no fake prod AD |
| Application-scoped permissions | **F** | Grants enforced + **admin grant CRUD** | `test_app_grants` + M15 | `/admin/users` |
| Service credentials | **F** | Create/rotate/**revoke** | enterprise + M15 | `/admin/users` |
| Audit log | **F** | Searchable admin audit | M15 | `/admin/audit` |
| Jobs + safe retry | **F** | Retry + sent-delivery refuse | M15 | `/admin/jobs` |
| Public banner | **F** | Prior | Prior | Banner demo |
| **M14 Impact analysis** | **F** | Prior harden | Prior | Publish flow |
| **M15 Admin workspace** | **F** | `admin_workspace` + UI shell | `test_admin_workspace` + AdminShell vitest | `/admin/*` |
| Monitoring / Teams APIs | **M** (non-goal) | Absent | — | About/LIMITATIONS |

\*Improved in M15.

---

## UI-configurable vs deployment-time

See [administration.md](./administration.md). **UI/API:** deps, infra create, CSV, SN poll/unmatched, templates, test notify, grants, role maps, service creds, job retry. **OpenShift/env only:** SMTP/SN/OIDC/LDAP/JWT secrets and most integration endpoints — status/redaction only in UI; no arbitrary secret editor.

---

## Prioritized remaining gaps

| Priority | Item |
|----------|------|
| High | Live OIDC/LDAP not usable until real IdP configured |
| Medium | Digest notification worker |
| Medium | SN events without ExternalCiLink stay impact-less |
| Medium | Directory-group → ApplicationGrant auto-provision still limited |
| Low | Deeper catalog owner/tag admin UX; graph visualization polish |
| Low | Postgres concurrency tests need `TEST_POSTGRES_URL` |

---

## Functional demo checklist (M15)

| Check | Command / action | Result |
|-------|------------------|--------|
| Full pytest (+ Postgres when available) | `make test` / `pytest tests -q` | **125 passed** |
| Web vitest + production build | `cd apps/web && npm test && npm run build` | **16 passed**, build OK |
| Lint | `make lint` | **All checks passed** |
| Admin demo | Login `admin@demo.example.com` / `password123` → **Admin** nav | Workspace sections load; publisher denied by API |

Local: `make install && make migrate && make api` / `make worker` / `make web`.  
Compose: `make compose-up` → http://localhost:8080.

---

## Category rollup

| Category | Notes |
|----------|-------|
| Fully functional | Lifecycle, recurrence, dashboard/calendar/ICS, subscriptions/SMTP/bridge, banner, grants, M14 impact, **M15 admin workspace** |
| Partially functional | Live enterprise IdP, digest worker, SN impact mapping without CI links |
| Stubbed | Digests, SN push |
| Missing / non-goal | Monitoring, Teams Graph APIs, native mobile |
