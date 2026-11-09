# MaintenanceHub repository docs

- [IMPLEMENTATION_AUDIT.md](./IMPLEMENTATION_AUDIT.md) — requirement map, categories, defects, demo checklist
- [LIMITATIONS.md](./LIMITATIONS.md) — incomplete / deferred capabilities (also shown on in-app About)
- [administration.md](./administration.md) — M15 Administration workspace; UI vs deployment-time config; environment catalog + dependency management
- [user-guide-alerts-calendar.md](./user-guide-alerts-calendar.md) — My Alerts subscribe/edit UX; Outlook subscribe vs Download `.ics`
- M16 consumer/publisher UX — My Applications, calendar agenda, four-step publish wizard, status URLs (see LIMITATIONS + IMPLEMENTATION_AUDIT)
- [recurrence.md](./recurrence.md) — M3b RRULE storage, occurrence identity/lifecycle, series scopes, phases, exception reconciliation
- [impact-analysis.md](./impact-analysis.md) — M14 dependency analysis, preview/confirm, revision tokens, authz
- [deploy-openshift.md](./deploy-openshift.md) — OpenShift secrets, AUTH_MODE, replicas, Postgres
- [banner-api.md](./banner-api.md) — public/internal banner JSON API, filtering, CORS/cache
- [banner-developer-guide.md](./banner-developer-guide.md) — JS/TS/JSON embed examples, local vs OpenShift routes, CORS/CSP troubleshooting, `embed.js`↔TS sync note
- Product architecture (PRD, ADRs, data model, API contracts, milestones) lives in the Project Agent Store; mirror here as needed.
