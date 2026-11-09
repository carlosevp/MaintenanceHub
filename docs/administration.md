# Administration workspace (M15)

Enterprise administrators use **Administration** (`/admin`) for catalog dependencies, ServiceNow/CMDB, notifications, users/permissions, jobs/delivery, and audit.

Authorization is enforced by the API (`platform_administrator`). Hiding nav is not a security boundary.

## Sections

| Section | Capabilities |
|---------|----------------|
| Overview | Catalog/job/delivery counts; redacted secrets/config status; OpenShift-only callouts |
| Apps, envs & deps | Environment catalog (create/edit/deactivate); Consumer→Provider dependency editor (cross-env); infra create; dependency list/delete |
| ServiceNow & CMDB | Status without secrets; connection test; dry-run / poll-now; unmatched resolve; CSV upload→preview→commit→history |
| Notifications | SMTP/bridge status; **Template Manager** (CRUD/clone/activate/versions); PA `To:` routing docs; preview + test send (capture vs real). See [power-automate-templates.md](./power-automate-templates.md). |
| Users & Permissions | Users; application grants; directory group→role maps; service credentials create/rotate/revoke |
| Jobs & Delivery | Job filters; safe retry; delivery history filters |
| Audit | Searchable immutable audit log |

## UI-configurable vs deployment-time

**Runtime-editable in the Administration UI (via API):**

- Environment catalog definitions (code, display name, description, sort order, active/inactive). Prefer deactivate over delete when referenced. Distinct from per-application deployment instances (`AppEnvironment`).
- Manual dependency edges (incl. cross-environment); consumer app grant required for non-admins. Direction is always Consumer depends on Provider — if the provider is affected, the consumer may also be impacted. Leaving environment blank means **environment-agnostic** (matches all environments on that side), not “unknown.”
- Infra component create
- Support groups / catalog objects already exposed by catalog APIs
- CSV import preview/commit (`import_mode` recorded; absences never deleted)
- SN dry-run / poll-now / unmatched resolve
- Notification templates (CRUD, clone, activate/deactivate/archive, restore, preview); test notifications (demo capture or real SMTP path)
- Application grants; group role mappings
- Service credentials (generate → one-time secret; rotate → new one-time secret; revoke; list/audit never expose secret)
- Job retry (failed/dead only; `FOR UPDATE`; refuses sent / UNCERTAIN / mid-send deliveries)

**Deployment-time / OpenShift Secrets only (status shown, not editable):**

- `SMTP_*` including password
- `SERVICENOW_*` including password, instance URL, query, poll interval
- Bridge mailbox / subject template env defaults
- `AUTH_MODE`, OIDC/LDAP endpoints and client/bind secrets
- `JWT_SECRET`

There is **no** arbitrary secret editor. Live AD/OIDC requires real IdP configuration — local_dev demo login is not production AD.

`GET /admin/secrets-status` returns `runtime_editable`, `deployment_only`, and `openshift_only` lists plus configured? flags — never password values.

## Delivery uncertainty

SMTP **acceptance** is recorded as `sent`. If the client loses the response after hand-off, the delivery is marked `sent` with an `UNCERTAIN:` error note. Admin retry of that delivery is refused to prevent duplicates. SMTP acceptance still does **not** mean confirmed Teams delivery (bridge).

## Partial CSV policy

Relationship imports never delete edges solely because they are absent from a partial export. Commit summaries include `absences_deleted: 0` and an explicit absence policy. Full-snapshot deletion remains unsupported; administrators delete edges explicitly when needed.

## History pagination

Jobs, deliveries, audit, and CSV import history support `limit` + `offset` filters. Indexes cover common admin list patterns (SQLite create_all + Alembic `f6a7b8c9d0e1`).

## Non-goals

- Monitoring / health of catalog apps
- Microsoft Graph or Teams APIs (bridge email only)
- ServiceNow writes / change approvals
- Fake production Active Directory login
