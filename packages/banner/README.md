# `@maintenancehub/banner`

Lightweight embeddable banner for **confirmed** planned maintenance and manual outages.

This is **not** a monitoring probe — it only displays messages published in MaintenanceHub.

## Security (browser embeds)

`GET /api/v1/public/banner` returns a **minimal public DTO** and may be called **without authentication**.

**Do not** put long-lived service `client_id` / `client_secret` values in frontend JavaScript, mobile apps, or public HTML. Those secrets belong only on a trusted server (BFF) or worker.

Optional Bearer tokens are for server-side callers (service credential with scope `banner:read`, or publisher/admin JWT).

## Install / build

```bash
cd packages/banner
npm install
npm run build
```

```ts
import { mountMaintenanceBanner } from "@maintenancehub/banner";
import "@maintenancehub/banner/style.css";
```

## Usage (browser — no secrets)

```html
<div id="mh-banner-root"></div>
<script type="module">
  import { mountMaintenanceBanner } from "./node_modules/@maintenancehub/banner/dist/index.js";

  mountMaintenanceBanner({
    target: "#mh-banner-root",
    apiBaseUrl: "https://maintenancehub.example.com",
    applicationKey: "payments-gateway",
    environmentKey: "PROD", // optional
    pollIntervalMs: 60000,
  });
</script>
```

### Server-side / BFF (optional token)

```ts
import { fetchBannerMessages } from "@maintenancehub/banner";

const messages = await fetchBannerMessages({
  apiBaseUrl: "http://localhost:8000",
  accessToken: shortLivedJwt, // never a client_secret
  applicationKey: "payments-gateway",
});
```

## Public DTO

Only: `id`, `kind`, `title`, `status`, `starts_at`, `ends_at`, `expected_impact`, `approval_state`.  
Internal notes / descriptions / timeline are **not** exposed.
