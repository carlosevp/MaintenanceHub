# `@maintenancehub/banner`

Lightweight embeddable banner for **confirmed** planned maintenance and manual outages (M12/M18).

This is **not** a monitoring probe — it only displays messages published in MaintenanceHub.

## Security (browser embeds)

`GET /api/v1/public/banner` returns a **minimal public DTO** and may be called **without authentication**.

**Do not** put long-lived service `client_id` / `client_secret` values in frontend JavaScript, mobile apps, or public HTML. Those secrets belong only on a trusted server (BFF) or worker.

Optional Bearer tokens are for server-side callers (service credential with scope `banner:read`, or publisher/admin JWT).

OpenShift in-cluster callers may use the stable path:

`GET /api/v1/internal/banner?application_key=…&environment_key=…`

(same DTO; prefer service DNS such as `http://maintenancehub-api:8000`).

## Install / build

```bash
cd packages/banner
npm install
npm run build
```

```ts
import { mountMaintenanceBanner, buildEmbedSnippet } from "@maintenancehub/banner";
import "@maintenancehub/banner/style.css";
```

## Dependency-free script tag (Claims INT / legacy hosts)

```html
<link rel="stylesheet" href="/vendor/maintenancehub-banner/style.css" />
<div id="mh-banner-root"></div>
<script src="/vendor/maintenancehub-banner/embed.js" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: "https://maintenancehub.example.com",
      applicationKey: "claims",
      environmentKey: "INT",
      theme: "light", // or "dark" | "auto"
      advanceHours: 24,
      pollIntervalMs: 60000,
    });
  });
</script>
```

No npm runtime dependencies. Host failures render a soft error; empty results hide the banner.

## TypeScript / ESM package

```ts
mountMaintenanceBanner({
  target: "#mh-banner-root",
  apiBaseUrl: "https://maintenancehub.example.com",
  applicationKey: "claims",
  environmentKey: "INT",
  theme: "auto",
  advanceHours: 24,
  pollIntervalMs: 60_000,
});
```

### Server-side / BFF (optional token)

```ts
import { fetchBannerMessages } from "@maintenancehub/banner";

const messages = await fetchBannerMessages({
  apiBaseUrl: "http://maintenancehub-api:8000",
  internal: true, // OpenShift-stable path
  accessToken: shortLivedJwt, // never a client_secret
  applicationKey: "claims",
  environmentKey: "INT",
});
```

## Behaviour

| Rule | Detail |
|------|--------|
| Exact app + env | Only confirmed impacts for that pair (incl. confirmed downstream) |
| No unrelated | Other applications never appear |
| Status labels | `upcoming` / `in_progress` / `extended` / `verifying` / `outage` |
| Never approved = outage | `approved_window` is excluded entirely |
| Advance window | Default 24h (`advance_hours` / `BANNER_ADVANCE_HOURS`) |
| Dismiss upcoming | localStorage; re-shows when `revision` changes (extend/update) |
| Active notices | Not dismissible |

## Public DTO

Safe fields only: `id`, `event_id`, `kind`, `title`, `status`, `presentation`, `starts_at`, `ends_at`, `expected_impact`, `approval_state`, `revision`, `dismissible`, `occurrence_starts_at`.

Internal notes / descriptions / timeline / secrets are **never** exposed.

## JSON API

```
GET /api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=24
GET /api/v1/internal/banner?application_key=claims&environment_key=INT
```

Response: `200` JSON array. CORS enabled for configured origins. `Cache-Control: public, max-age=30`. Public path is rate-limited per client IP.
