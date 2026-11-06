# `@maintenancehub/banner`

Lightweight embeddable banner for **confirmed** planned maintenance and manual outages (M12/M18 harden).

This is **not** a monitoring probe — it only displays messages published in MaintenanceHub.

## Security

- Public DTO may be fetched **without** auth. **Never** put `client_secret` in browsers.
- XSS-safe escaped text; CSS scoped to `.mh-banner*`.
- Browser snippets should use **HTTPS** corporate bases. Local / in-cluster URLs warn.

## Compact UX

By default the banner shows **one primary** notice (highest priority) plus **View N additional**.
Expanded mode lists all. Upcoming notices are dismissible; `revision` changes re-show them.

## Install / build

```bash
cd packages/banner && npm install && npm run build
```

## Browser snippet (Claims INT)

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
      timeZone: "America/Chicago", // optional IANA; default = viewer
      statusPageBaseUrl: "https://maintenancehub.example.com",
      theme: "light",
      compact: true,
      pollIntervalMs: 60000,
    });
  });
</script>
```

Independent host demo: `examples/independent-host.html`.

## TypeScript

```ts
import { mountMaintenanceBanner, buildEmbedSnippet, formatWindowIntl } from "@maintenancehub/banner";
import "@maintenancehub/banner/style.css";
```

API returns ISO-8601; UI formats via `Intl` (`formatWindowIntl`).

## Routes

| Kind | Use |
|------|-----|
| Browser / corporate | `https://…/api/v1/public/banner` |
| In-cluster | `http://maintenancehub-api:8000/api/v1/internal/banner` (BFF only) |
| Local | `http://127.0.0.1:8000` — demos only |

See `docs/banner-api.md` for CORS, CSP, filtering, and multi-notice policy.
