# Administration workspace (M15)

Enterprise administrators use **Administration** (`/admin`) for catalog dependencies, ServiceNow/CMDB, notifications, users/permissions, jobs/delivery, and audit.

Authorization is enforced by the API (`platform_administrator`). Hiding nav is not a security boundary.

## Sections

| Section | Capabilities |
|---------|----------------|
| Overview | Catalog/job/delivery counts; redacted secrets/config status; OpenShift-only callouts |
| Apps & Dependencies | Consumer→Provider editor (cross-env), infra create, dependency list/delete |
| ServiceNow & CMDB | Status without secrets; connection test; dry-run / poll-now; unmatched resolve; CSV upload→preview→commit→history |
| Notifications | SMTP/bridge status; template edit; test send with subject/body preview |
| Users & Permissions | Users; application grants; directory group→role maps; service credentials create/rotate/revoke |
| Jobs & Delivery | Job filters; safe retry; delivery history filters |
| Audit | Searchable immutable audit log |

## UI-configurable vs deployment-time

**Configurable in the Administration UI (via API):**

- Manual dependency edges (incl. cross-environment)
- Infra component create
- Support groups / catalog objects already exposed by catalog APIs
- CSV import preview/commit
- SN dry-run / poll-now / unmatched resolve
- Notification templates; test notifications
- Application grants; group role mappings
- Service credentials (secret shown once on create/rotate)
- Job retry (failed/dead only; refuses already-sent deliveries)

**Deployment-time / OpenShift Secrets only (status shown, not editable):**

- `SMTP_*` including password
- `SERVICENOW_*` including password, instance URL, query, poll interval
- Bridge mailbox / subject template env defaults
- `AUTH_MODE`, OIDC/LDAP endpoints and client/bind secrets
- `JWT_SECRET`

There is **no** arbitrary secret editor. Live AD/OIDC requires real IdP configuration — local_dev demo login is not production AD.

## Partial CSV policy

Relationship imports never delete edges solely because they are absent from a partial export. Full vs partial is distinguished in import options/history; administrators delete edges explicitly when needed.

## Non-goals

- Monitoring / health of catalog apps
- Microsoft Graph or Teams APIs (bridge email only)
- ServiceNow writes / change approvals
- Fake production Active Directory login
