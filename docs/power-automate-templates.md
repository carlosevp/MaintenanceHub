# Power Automate notification templates (M19)

MaintenanceHub sends **email only** (SMTP or the Power Automate email bridge). There is **no** Microsoft Graph, Teams webhook, or Teams API integration.

Admins manage templates under **Administration → Notifications** (capability `notification_admin`).

## Roles

| Piece | Meaning |
|-------|---------|
| **SMTP To** | Envelope recipient — for Teams bridge sends this is the configured **bridge mailbox**. |
| **Body `To: …` line** | **Power Automate routing** — the flow parses this address and posts to the matching Teams channel/chat. It is **not** the SMTP To header. |
| **Subject** | Filter/trigger for the flow. PA sample default: `[TEAMS] Maintenance Alert`. |

## Sample system template: `pa.teams_alert`

- **Subject:** `[TEAMS] Maintenance Alert`
- **Plain body (start):**

```text
To: {{teams_target_email}}

MaintenanceHub notice (human-published — not monitoring).
…
```

Placeholders use `{{name}}` (Power Automate style). Legacy `{name}` still works.

## Configure the Power Automate flow

1. **Trigger:** When a new email arrives in the bridge mailbox (Outlook / Office 365).
2. **Condition (recommended):** Subject equals / starts with `[TEAMS] Maintenance Alert`  
   (or contains your org’s subject convention).
3. **Parse routing address from the body:**
   - Take the email body (prefer plain text).
   - Find the first line matching `To: <email>`.
   - Extract the email (trim whitespace).
4. **Post to Teams** using that address (channel email / user) via the **Teams** connector actions your tenant allows — still driven by email content, not by MaintenanceHub calling Graph.
5. **Ignore SMTP To** for channel selection; it only delivers mail into the bridge mailbox.

### Example expression sketch

```text
first(split(first(split(triggerOutputs()?['body/body'], 'To: '))[1], '\n'))
```

(Adapt to your trigger’s body field; strip HTML if the message is multipart.)

## Admin UI workflow

1. Open `/admin/notifications`.
2. Select `pa.teams_alert` (or clone it).
3. Edit subject / plain / HTML; use the placeholder picker.
4. **Preview** with a sample `teams_target_email`.
5. **Test send (demo capture)** — with `MH_NOTIFICATION_CAPTURE_DIR` set, messages are written as JSON under that directory (no real SMTP).
6. **Test send (real path)** — uses SMTP when enabled; otherwise the log sink.
7. Save creates a **version**; restore from history; deactivate without deleting system templates.

## Worker behavior

Lifecycle / reminder jobs resolve the **active** template for the event type, render subject + plain + HTML (HTML values escaped), and **persist `rendered_payload` on the delivery row before send**. Bridge sends keep the rendered PA subject when the template is PA-style; legacy templates still use `[MH-ROUTE:{channel_key}] {title}` subject tokens.

## Security notes

- Substituted placeholder values are HTML-escaped in HTML bodies.
- Admin HTML fragments are sanitized (script/style/`on*`/javascript: URLs stripped).
- Template mutations are admin-only and audited (`notification_template.*`).
