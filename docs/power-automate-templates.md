# Power Automate notification templates (M19)

MaintenanceHub sends **email only** (SMTP or the Power Automate email bridge). There is **no** Microsoft Graph, Teams webhook, or Teams API integration.

Admins manage templates under **Administration → Notifications** (capability `notification_admin`) using **Edit / Preview / Test** tabs.

**SMTP/log `sent` is never Teams delivery confirmation.** Power Automate (and Teams) confirm channel delivery separately. In-app `teams_delivery_confirmed` stays `false`.

## Contract

| Piece | Default | Meaning |
|-------|---------|---------|
| **Subject** | `[TEAMS] Maintenance Alert` | Flow trigger / filter. |
| **SMTP To** | Bridge mailbox (`BRIDGE_MAILBOX` / `MH` bridge settings) | Envelope recipient only. |
| **Body first line** | `To: {{teams_target_email}}` | **Power Automate Teams routing** — **not** the SMTP To header. |

Saving a PA template (key `pa.*`, channel `bridge`, or subject/body matching the contract) **re-applies** the routing envelope if body edits strip the `To:` line. Plain and HTML must both yield the same routing address after render. SMTP To must never equal the body routing email.

### Admin-configurable PA subject (no code change)

MaintenanceHub ships the **default** subject `[TEAMS] Maintenance Alert`. Operators configure the **Power Automate flow condition** to match that subject (equals / starts with) in the tenant admin UI — **no MaintenanceHub code change** is required to align the flow filter with the shipped contract. If your org standardizes on a different trigger string later, update the PA condition and the active MH template subject together via admin process; keep SMTP To = bridge mailbox and body `To:` = Teams route.

## Exact email the bridge receives (rendered sample)

After placeholders render, a real message looks like this. **Outlook/SMTP `To:`** = bridge mailbox. **First body line `To:`** = Teams route for PA.

### Envelope

```text
From: maintenancehub@example.com
To: bridge-mailbox@example.com
Subject: [TEAMS] Maintenance Alert
```

### Plain-text body (preferred for PA parse)

```text
To: ops-payments-channel@example.com

MaintenanceHub notice (human-published — not monitoring).

Title: Claims INT batch window
Status: in_progress
Communication: Confirmed (confirmed_scheduled)
Window: 2026-11-10T02:00:00Z → 2026-11-10T04:00:00Z (America/Chicago)
Impact: Brief read-only
Channel: ops-payments
Detail: https://mh.example.com/events/…

Power Automate: parse the first body line `To: <email>` as the Teams
routing address. The SMTP envelope recipient is the bridge mailbox.
```

### HTML alternative (multipart)

```html
<p><strong>To:</strong> ops-payments-channel@example.com</p>
<p>MaintenanceHub notice (human-published — not monitoring).</p>
<ul>
<li><strong>Title:</strong> Claims INT batch window</li>
<li><strong>Status:</strong> in_progress</li>
<li><strong>Window:</strong> 2026-11-10T02:00:00Z → 2026-11-10T04:00:00Z (America/Chicago)</li>
<li><strong>Impact:</strong> Brief read-only</li>
<li><strong>Channel:</strong> ops-payments</li>
</ul>
<p><a href="https://mh.example.com/events/…">Open in MaintenanceHub</a></p>
<p><em>PA: first <code>To:</code> line is routing, not SMTP To.</em></p>
```

Template source still uses `{{teams_target_email}}` / `{{title}}` / … before render. HTML substituted values are escaped; admin HTML fragments are sanitized.

## Exact Power Automate flow example

Assumes Office 365 Outlook + Teams connectors in your tenant.

### 1. Trigger

**When a new email arrives (V3)**  
- Folder: Inbox (bridge mailbox)  
- Only with attachments: No  

### 2. Condition — subject trigger (admin-configurable)

**Condition** → Subject **starts with** / **equals** (match the MH default unless your org changed the contract):

```text
[TEAMS] Maintenance Alert
```

If false → terminate (Succeeded).

### 3. Compose — extract Teams routing from body

Prefer **plain text body**. Expression (Power Automate):

```text
trim(
  first(
    split(
      first(
        skip(
          split(coalesce(triggerOutputs()?['body/body'], ''), 'To:'),
          1
        )
      ),
      decodeUriComponent('%0A')
    )
  )
)
```

Simpler if you store the body in Compose `BodyText` first:

```text
trim(first(split(first(skip(split(outputs('BodyText'), 'To:'), 1)), decodeUriComponent('%0A'))))
```

Name the Compose output e.g. `TeamsRouteEmail`.

**Do not** use the Outlook **To** header — that is the bridge mailbox (SMTP envelope).

### 4. Post to Teams

Use your org’s approved action, for example:

- **Post message in a chat or channel** with recipient = `outputs('TeamsRouteEmail')`, or  
- **Send an email** to the channel email address from Compose  

Message body can reuse the remainder of the MaintenanceHub email (everything after the routing line).

### 5. Acceptance criteria checklist

- [ ] Flow only runs when subject matches the PA subject contract (default `[TEAMS] Maintenance Alert`)  
- [ ] Teams destination comes from body `To:` line  
- [ ] Bridge mailbox is never used as the Teams route  
- [ ] SMTP/`sent` in MaintenanceHub ≠ confirmed Teams delivery  

## Admin UI workflow

1. `/admin/notifications` → select `pa.teams_alert`  
2. **Edit** — routing block protected; edit content + HTML (source / safe preview); placeholder picker  
3. **Preview** — realistic sample; routing vs content separated  
4. **Test** — **demo capture** never dials external SMTP; **real path** is admin-only  
5. Save → new version; restore from history; deactivate (system templates cannot archive)

## Worker behavior

Lifecycle jobs (create/schedule, remind, extend, cancel, complete/transition) resolve the **active** template deterministically:

1. Active row with `key == event_type`  
2. Else active rows with matching `event_type`, ordered by `key` ASC  

Rendered subject/plain/HTML + `template_id` / `template_version` are persisted on the delivery **before send**. Retries reuse that payload and **do not** switch versions. Later template edits only affect new deliveries.

## Config vars (first real bridge test)

| Variable | Role |
|----------|------|
| `SMTP_ENABLED=true` | Real envelope send (otherwise log/capture sink) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | Relay |
| `BRIDGE_ENABLED=true` | Allow Teams-via-email bridge path |
| `BRIDGE_MAILBOX` | **SMTP To** (bridge inbox the PA flow watches) |
| `MH_NOTIFICATION_CAPTURE_DIR` | Optional demo capture dir (never required for real send) |
| `PUBLIC_BASE_URL` | Links inside templates |

## Security / status notes

- Substituted values HTML-escaped; fragments sanitized  
- Template mutations audited (`notification_template.*`)  
- Delivery `status=sent` means SMTP/log **acceptance** only — never “Teams delivered”  
