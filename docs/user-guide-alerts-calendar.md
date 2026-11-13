# My Alerts & Outlook calendars

Consumer guide for `/alerts` (also linked as **My Alerts**).

## Subscribe to maintenance notices

1. Search and select an **application** (catalog display name — never a database ID).
2. Choose **selected environments** (multi-select) or the **entire application**.
3. Pick advance reminders: **24 hours**, **4 hours**, **1 hour**, **30 minutes**, and/or **5 minutes** before start.
4. Choose lifecycle notices: **Start**, **Extension**, **Cancellation**, **Completion**.
5. Confirm the notification channel (Email or Teams via email bridge).
6. Review Active alerts — edit or unsubscribe anytime.

Matching uses effective impacts: an `app + environment` alert fires only when the same pair appears on the maintenance impact set. Authorization and subscription ownership are unchanged.

If a catalog application or environment was removed, Active alerts show a clear “unknown / removed” label instead of a raw ID.

## Outlook calendar — two options

Under **Outlook calendar**, optionally enable **Include calendar alerts**. When on, generated ICS includes `VALARM` reminders using the same advance offsets from your My Alerts subscriptions (for events that match those app/environment pairs). Cancelled events omit alarms. Email/Teams notification delivery is unchanged — calendar alerts are local to Outlook (or any ICS client).

### Option A: Subscribe (refreshable feed)

Create a tokenized ICS feed scoped to your favorites and subscriptions. Revoke anytime. The feed remembers whether calendar alerts were enabled at create time.

**Outlook on the web** fetches from Microsoft cloud. A localhost, `127.0.0.1`, or internal-only OpenShift URL is generally **not** reachable from that path — even if a corporate browser can open MaintenanceHub. MaintenanceHub does not expose an internal proxy. Configure `PUBLIC_BASE_URL` to a browser-appropriate **HTTPS** base that Microsoft cloud can reach, or use Option B.

### Option B: Download calendar (`.ics`)

Use **Download calendar (.ics)** for an authenticated snapshot. Default scope is your **favorites and active subscriptions**. If you have neither, the file is still a valid empty calendar — or choose **Or download one application** for an app-specific snapshot without creating an alert. No public calendar endpoint is required. The same calendar-alerts checkbox applies to the download.

Confirmed maintenance appears as confirmed (`STATUS:CONFIRMED`); approved windows that are not yet confirmed appear as tentative (`STATUS:TENTATIVE`, title prefixed with `[Approved window]`). Recurrence (`RRULE` / `EXDATE` / `RECURRENCE-ID`), timezones, and friendly titles follow the shared ICS generator.

> Downloaded calendars are static snapshots. New maintenance and later changes will not automatically appear. Download again to get an updated copy.

**Outlook on the web import (concise):** Calendar → Add calendar → Upload from file → choose the `.ics`. Re-import does not reliably reconcile prior events unless your tenant merges by UID — treat each file as a fresh snapshot.
