# MaintenanceHub implementation audit

**Branch audited:** `cursor/m16-consumer-publisher-932e` (M16 Consumer & Publisher Experience; base hardened PR #10 / `cursor/m15-admin-workspace-04a5` @ `c77f5b4`)  
**Sources of truth:** Project store product-brief / PRD / ADRs / data-model / api-contracts / milestone-plan; repo `docs/LIMITATIONS.md`, `docs/administration.md`; actual source (not class existence alone).  
**Date:** 2026-11-06

## Executive summary

MaintenanceHub delivers a working **communication** stack for planned maintenance and manual outages (catalog → schedule → dashboard/calendar → subscriptions/SMTP/bridge → ICS → SN poll/CSV → banner → M3b recurrence → sparse occurrence lifecycle → M14 impact analysis → M15 Administration workspace → **M16 Consumer & Publisher Experience**). It is **not** a monitoring product.

**M16** personalizes the consumer homepage (**My Applications**), adds calendar agenda/filters, a four-step publisher wizard with drafts/templates/Quick Publish, richer subscription targeting (`app_environment`, multi-reminders), clearer notification templates, and authenticated shareable status URLs. Confirmed≠approved semantics and impact-revision safety from M14 are preserved.

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
| **M16 Consumer/publisher UX** | **F** | status_pages + dashboard/calendar slices + wizard/subs UI | `test_m16_consumer_publisher` | My Applications, Calendar agenda, Publish wizard, Status, Subscriptions |
| **M17 UX redesign / profiles** | **F** | experience registry + token theme + Overview/Alerts IA | `test_m17_experience` | Overview, Calendar, My Alerts, Schedule CTA, Admin gated |
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

## Functional demo checklist (M16)

| Check | Command / action | Result |
|-------|------------------|--------|
| Full pytest (+ Postgres when available) | `make test` / `pytest tests -q` | See M16 delivery |
| Web vitest + production build | `cd apps/web && npm test && npm run build` | See M16 delivery |
| Lint | `make lint` | See M16 delivery |
| My Applications | Login viewer → homepage favorites + extensions/cancels | Journeys A/I |
| Publisher wizard | `/events/new` four steps + Quick Publish | Journeys C/D |
| Status URLs | `/status/apps/{key}` / events / scheduled | Journey H |
| Admin still gated | Publisher blocked from `/admin` APIs | Journey J |

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
