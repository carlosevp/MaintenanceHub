# My Alerts & Outlook calendars

Consumer guide for `/alerts` (also linked as **My Alerts**).

## Subscribe to maintenance notices

1. Search and select an **application** (catalog display name — never a database ID).
2. Choose **selected environments** (multi-select) or the **entire application**.
3. Pick advance reminders: **24 hours**, **4 hours**, and/or **30 minutes** before start.
4. Choose lifecycle notices: **Start**, **Extension**, **Cancellation**, **Completion**.
5. Confirm the notification channel (Email or Teams via email bridge).
6. Review Active alerts — edit or unsubscribe anytime.

Matching uses effective impacts: an `app + environment` alert fires only when the same pair appears on the maintenance impact set. Authorization and subscription ownership are unchanged.

If a catalog application or environment was removed, Active alerts show a clear “unknown / removed” label instead of a raw ID.

## Outlook calendar — two options

### Option A: Subscribe (refreshable feed)

Create a tokenized ICS feed scoped to your favorites and subscriptions. Revoke anytime.

**Outlook on the web** fetches from Microsoft cloud. A localhost, `127.0.0.1`, or internal-only OpenShift URL is generally **not** reachable from that path — even if a corporate browser can open MaintenanceHub. MaintenanceHub does not expose an internal proxy. Configure `PUBLIC_BASE_URL` to a browser-appropriate **HTTPS** base that Microsoft cloud can reach, or use Option B.

### Option B: Download calendar (`.ics`)

Use **Download calendar (.ics)** for an authenticated snapshot of upcoming maintenance for your subscriptions. No public calendar endpoint is required.

> Downloaded calendars are static snapshots. New maintenance and later changes will not automatically appear. Download again to get an updated copy.

**Outlook on the web import (concise):** Calendar → Add calendar → Upload from file → choose the `.ics`. Re-import does not reliably reconcile prior events unless your tenant merges by UID — treat each file as a fresh snapshot.
