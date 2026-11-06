# Banner developer guide (M18)

Embed **confirmed** maintenance/outage notices into host apps with `@maintenancehub/banner` or the dependency-free `embed.js` IIFE.

> Communication only — not monitoring. Never put `client_secret` / long-lived credentials in browser JavaScript.

## Routes

| Kind | Who | Base + path |
|------|-----|-------------|
| **Browser / corporate** | End-user browsers | `https://<PUBLIC_BASE>/api/v1/public/banner` |
| **Local demo** | Developers | `http://127.0.0.1:8000/api/v1/public/banner` — never ship |
| **OpenShift in-cluster** | BFF / pod only | `http://maintenancehub-api:8000/api/v1/internal/banner` — **never** use k8s DNS from browsers |

Configure the corporate HTTPS origin via `PUBLIC_BASE_URL` (API) and the Embed screen “Browser / corporate API base”.

Static assets (browser):

```
https://<PUBLIC_BASE>/static/banner/embed.js
https://<PUBLIC_BASE>/static/banner/style.css
```

## JSON (public DTO)

```http
GET /api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=24
```

```json
[
  {
    "id": "…",
    "event_id": "…",
    "kind": "planned_maintenance",
    "title": "Claims INT window",
    "status": "scheduled",
    "presentation": "upcoming",
    "starts_at": "2026-11-07T02:00:00Z",
    "ends_at": "2026-11-07T04:00:00Z",
    "expected_impact": "Brief read-only",
    "approval_state": "confirmed_scheduled",
    "revision": "…",
    "dismissible": true,
    "occurrence_starts_at": null,
    "status_path": "/status/events/…"
  }
]
```

Timestamps are **UTC ISO-8601**. UIs format with `Intl` + optional IANA `timeZone`.  
`status_path` is relative — prefix with the same HTTPS corporate UI origin so Status links are reachable.

Auth is optional for this DTO. If a service JWT is sent, it must include scope `banner:read`.

## TypeScript package

```bash
cd packages/banner && npm install && npm test && npm run build
```

```ts
import {
  mountMaintenanceBanner,
  buildEmbedSnippet,
  formatWindowIntl,
} from "@maintenancehub/banner";
import "@maintenancehub/banner/style.css";

mountMaintenanceBanner({
  target: "#mh-banner-root",
  apiBaseUrl: "https://maintenancehub.example.com", // HTTPS corporate — not k8s DNS
  applicationKey: "claims",
  environmentKey: "INT",
  timeZone: "America/Chicago",
  statusPageBaseUrl: "https://maintenancehub.example.com",
  compact: true,
  pollIntervalMs: 60_000,
});
```

## Dependency-free JS (copy-paste)

```html
<link rel="stylesheet" href="https://maintenancehub.example.com/static/banner/style.css" />
<div id="mh-banner-root"></div>
<script src="https://maintenancehub.example.com/static/banner/embed.js" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: "https://maintenancehub.example.com",
      applicationKey: "claims",
      environmentKey: "INT",
      timeZone: "America/Chicago",
      statusPageBaseUrl: "https://maintenancehub.example.com",
      compact: true,
      pollIntervalMs: 60000,
    });
  });
</script>
```

Independent host smoke page: `packages/banner/examples/independent-host.html`.

### `embed.js` ↔ TypeScript sync limitation

`packages/banner/src/embed.js` is a **hand-maintained IIFE** that mirrors `src/index.ts` for hosts that cannot use ESM/npm. There is **no automatic compile step** from TS → IIFE. When changing banner behavior (compact UX, dismiss, Intl, fetch paths), update **both** files and run `npm test` + `npm run build` (build copies `embed.js` into `dist/`).

## Filtering / UX rules (summary)

- Exact `application_key` (+ optional `environment_key`); confirmed impacts only (incl. confirmed downstream).
- Deduplicate by **logical occurrence** (`event_id` + occurrence slot) — not by title. Separate events with the same title remain separate.
- Never treat `approved_window` as an outage.
- Compact: one primary notice + “View N additional”.
- Upcoming dismissible; re-shows when `revision` changes (extend/update).

## CORS / CSP troubleshooting

**CORS:** set `API_CORS_ORIGINS` to the host origin(s) that call the public API (e.g. `https://claims-int.example.com`). Browsers calling from an origin not on that list fail with a network/CORS error → banner soft-fails (“Unable to load…”).

**CSP (host):** allow script/style/connect to the HTTPS MaintenanceHub origin. Prefer nonces for the mount script. See [banner-api.md](./banner-api.md).

**Wrong base:** if the snippet uses `http://maintenancehub-api:8000`, browsers cannot resolve cluster DNS. Use the corporate HTTPS route for embeds; keep `/internal/banner` for BFFs.

**Status 404/401:** ensure `statusPageBaseUrl` points at a reachable MH UI and the viewer can open `/status/events/…`.

## Local OpenShift-style check

```bash
# Public (browser-shaped)
curl -s "http://127.0.0.1:8000/api/v1/public/banner?application_key=claims&environment_key=INT"

# Internal (BFF-shaped)
curl -s "http://127.0.0.1:8000/api/v1/internal/banner?application_key=claims&environment_key=INT"

# Assets
curl -sI "http://127.0.0.1:8000/static/banner/embed.js"
```

In-app: **Embed banner** (`/banner-demo`) — Claims / INT — copy snippet (defaults to HTTPS corporate base).
