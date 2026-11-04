# `@maintenancehub/banner`

Lightweight embeddable banner for **confirmed** planned maintenance and manual outages.

This is **not** a monitoring probe — it only displays messages published in MaintenanceHub.

## Install / build

```bash
cd packages/banner
npm install
npm run build
```

Import from the built package (or path to `src` in a monorepo):

```ts
import { mountMaintenanceBanner } from "@maintenancehub/banner";
import "@maintenancehub/banner/style.css";
```

## Usage

1. Create a **service credential** with scope `banner:read` (Admin → or `POST /api/v1/admin/service-credentials`).
2. Obtain a token: `POST /api/v1/auth/service/token` with `client_id` / `client_secret`.
3. Mount the banner:

```html
<div id="mh-banner-root"></div>
<script type="module">
  import { mountMaintenanceBanner } from "./node_modules/@maintenancehub/banner/dist/index.js";

  mountMaintenanceBanner({
    target: "#mh-banner-root",
    apiBaseUrl: "https://maintenancehub.example.com",
    accessToken: "SERVICE_JWT",
    applicationKey: "payments-gateway",
    environmentKey: "PROD", // optional
    pollIntervalMs: 60000,
  });
</script>
```

### Fetch only

```ts
import { fetchBannerMessages } from "@maintenancehub/banner";

const messages = await fetchBannerMessages({
  apiBaseUrl: "http://localhost:8000",
  accessToken: token,
  applicationKey: "payments-gateway",
  environmentKey: "PROD",
});
```

## Public DTO

Only: `id`, `kind`, `title`, `status`, `starts_at`, `ends_at`, `expected_impact`, `approval_state`.  
Internal notes / descriptions / timeline are **not** exposed.
