# Banner JSON API (M12 / M18)

Public, dependency-free embeds for confirmed maintenance and outage notices.

> Communication only — not a monitoring product.

## Endpoints

### Public (browser / CDN edge)

```
GET /api/v1/public/banner
```

Query parameters:

| Param | Required | Description |
|-------|----------|-------------|
| `application_key` | yes | Exact application key (e.g. `claims`) |
| `environment_key` | no | Exact environment key (e.g. `INT`). When set, only that app+env pair matches. |
| `advance_hours` | no | Upcoming horizon (0–168). Default `BANNER_ADVANCE_HOURS` (24). |

### Internal (OpenShift-stable)

```
GET /api/v1/internal/banner
```

Same query parameters and DTO. Prefer in-cluster service DNS:

`http://maintenancehub-api:8000/api/v1/internal/banner?application_key=claims&environment_key=INT`

## Auth

- **Optional** for the minimal public DTO (browser embeds).
- Service credentials that *do* authenticate must include scope `banner:read`.
- **Never** place `client_secret` in frontend HTML/JS.

## Filtering rules

1. Exact `application_key` (+ optional `environment_key`) against **confirmed** effective impacts (series or occurrence overrides), including **confirmed downstream** apps.
2. Unrelated applications never appear.
3. `approval_state=approved_window` is excluded — **never** treated as an outage.
4. Cancelled / completed occurrences are excluded.
5. Active executing windows and upcoming windows within the advance horizon are included.
6. Presentation labels: `upcoming` | `in_progress` | `extended` | `verifying` | `outage`.

## Response DTO (safe fields only)

```json
[
  {
    "id": "evt_or_occurrence_id",
    "event_id": "…",
    "kind": "planned_maintenance",
    "title": "Claims INT batch",
    "status": "scheduled",
    "presentation": "upcoming",
    "starts_at": "2026-11-07T02:00:00Z",
    "ends_at": "2026-11-07T04:00:00Z",
    "expected_impact": "Read-only",
    "approval_state": "confirmed_scheduled",
    "revision": "2026-11-07T04:00:00+00:00|scheduled|…",
    "dismissible": true,
    "occurrence_starts_at": null
  }
]
```

Never includes: `description`, timeline/notes, secrets, credentials.

## Cache / CORS / rate limit

- CORS: `API_CORS_ORIGINS`
- Public: `Cache-Control: public, max-age=BANNER_CACHE_MAX_AGE_SECONDS` (default 30), rate-limited per client IP (`BANNER_RATE_LIMIT_PER_MINUTE`, default 60)
- Internal: `Cache-Control: private, max-age=15`

## Static embed assets

```
GET /static/banner/embed.js
GET /static/banner/style.css
```

## Claims INT embed

See `@maintenancehub/banner` README and `packages/banner/examples/claims-int.html`.
In the web app: **Embed banner** (`/banner-demo`) — select Claims / INT, copy snippet, preview light/dark.
