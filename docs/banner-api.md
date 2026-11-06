# Banner JSON API (M12 / M18 harden)

Public, dependency-free embeds for confirmed maintenance and outage notices.

> Communication only — not a monitoring product.

## Endpoints

### Public (browser / corporate HTTPS edge)

```
GET /api/v1/public/banner
```

| Param | Required | Description |
|-------|----------|-------------|
| `application_key` | yes | Exact application key (e.g. `claims`) |
| `environment_key` | no | Exact environment key (e.g. `INT`) |
| `advance_hours` | no | Upcoming horizon (0–168). Default `BANNER_ADVANCE_HOURS` (24). |

### Internal (OpenShift / in-cluster)

```
GET /api/v1/internal/banner
```

Same query + DTO. Prefer service DNS from a BFF — **not** from browsers:

`http://maintenancehub-api:8000/api/v1/internal/banner?application_key=claims&environment_key=INT`

## Route kinds

| Kind | Who | Base |
|------|-----|------|
| `browser` / corporate | End-user browsers | `https://maintenancehub.example.com` |
| `in_cluster` | OpenShift pods / BFF | `http://maintenancehub-api:8000` + `/internal/banner` |
| `local_dev` | Developers only | `http://127.0.0.1:8000` — never ship |

Snippet builders warn on local / non-HTTPS / in-cluster bases used as browser URLs.

## Auth

- Optional for the minimal public DTO.
- Authenticating service credentials need `banner:read`.
- **Never** place `client_secret` in frontend HTML/JS.

## Filtering & multi-notice policy

1. Exact app(+env) against **confirmed** effective impacts (incl. confirmed downstream).
2. Unrelated applications never appear.
3. `approved_window` excluded — never outage.
4. Deduplicate by **logical occurrence** (`event_id` + `occurrence_starts_at` / id) — **not** by title.
5. Deterministic order: outage → extended → in_progress → verifying → upcoming, then `starts_at`, then `id`.
6. Compact UI shows index `0` as primary; remaining via “View additional”.

## Response DTO

Timestamps are **UTC ISO-8601** (`…Z`). UIs format with `Intl` + optional IANA zone.

Safe fields: `id`, `event_id`, `kind`, `title`, `status`, `presentation`, `starts_at`, `ends_at`, `expected_impact`, `approval_state`, `revision`, `dismissible`, `occurrence_starts_at`, `status_path`.

Never: `description`, timeline/notes, secrets.

## Cache / CORS / rate limit

- CORS: `API_CORS_ORIGINS` (include corporate HTTPS origins that embed the banner).
- Public: `Cache-Control: public, max-age=…`; per-IP rate limit.
- Internal: `Cache-Control: private, max-age=15`.

## CSP (host)

Example for an independent host loading MH static assets + calling the public API:

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' https://maintenancehub.example.com 'nonce-…';
  style-src 'self' https://maintenancehub.example.com;
  connect-src 'self' https://maintenancehub.example.com;
  img-src 'self' data:;
```

- Prefer nonces over `'unsafe-inline'` for the mount script.
- Banner CSS is scoped under `.mh-banner*` — it must not restyle the host.
- All text nodes are HTML-escaped (XSS-safe).

## Graceful failure

Network/CORS/5xx → soft “Unable to load maintenance notices.” Empty → hidden region. Dismissed upcoming reappear when `revision` changes (extend/update).

## Static assets

```
GET /static/banner/embed.js
GET /static/banner/style.css
```

## Claims INT

See `@maintenancehub/banner` README, `examples/independent-host.html`, and the in-app **Embed banner** screen.
