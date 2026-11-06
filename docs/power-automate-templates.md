# Power Automate notification templates (M19)

MaintenanceHub sends **email only** (SMTP or the Power Automate email bridge). There is **no** Microsoft Graph, Teams webhook, or Teams API integration.

Admins manage templates under **Administration → Notifications** (capability `notification_admin`) using **Edit / Preview / Test** tabs.

## Contract (protected on save)

| Piece | Value | Meaning |
|-------|-------|---------|
| **Subject** | `[TEAMS] Maintenance Alert` | Flow trigger / filter. Locked for PA templates. |
| **SMTP To** | Bridge mailbox (`BRIDGE_MAILBOX`) | Envelope recipient only. |
| **Body first line** | `To: {{teams_target_email}}` | **Power Automate Teams routing** — not the SMTP To header. |

Saving a PA template (key `pa.*`, channel `bridge`, or subject/body matching the contract) **re-applies** this envelope if body edits strip the routing line. Plain and HTML must both yield the same routing address after render. SMTP To must never equal the body routing email.

## Sample system template: `pa.teams_alert`

```text
Subject: [TEAMS] Maintenance Alert

To: {{teams_target_email}}

MaintenanceHub notice (human-published — not monitoring).

Title: {{title}}
Status: {{status}}
…
```

Placeholders: `{{name}}` (preferred) or legacy `{name}`. HTML values are escaped; admin HTML is sanitized.

## Exact Power Automate flow example

Assumes Office 365 Outlook + Teams connectors in your tenant.

### 1. Trigger

**When a new email arrives (V3)**  
- Folder: Inbox (bridge mailbox)  
- Only with attachments: No  

### 2. Condition — subject trigger

**Condition** → Subject **starts with** / **equals**:

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

- [ ] Flow only runs when subject is `[TEAMS] Maintenance Alert`  
- [ ] Teams destination comes from body `To:` line  
- [ ] Bridge mailbox is never used as the Teams route  
- [ ] SMTP/`sent` in MaintenanceHub ≠ confirmed Teams delivery  

## Admin UI workflow

1. `/admin/notifications` → select `pa.teams_alert`  
2. **Edit** — routing block is read-only; edit content + HTML (source / safe preview); placeholder picker  
3. **Preview** — realistic sample; routing vs content separated  
4. **Test** — **demo capture** never dials external SMTP; **real path** is admin-only  
5. Save → new version; restore from history; deactivate (system templates cannot archive)

## Worker behavior

Lifecycle jobs (create/schedule, remind, extend, cancel, complete/transition) resolve the **active** template deterministically:

1. Active row with `key == event_type`  
2. Else active rows with matching `event_type`, ordered by `key` ASC  

Rendered subject/plain/HTML + `template_id` / `template_version` are persisted on the delivery **before send**. Retries reuse that payload and **do not** switch versions. Later template edits only affect new deliveries.

## Security / status notes

- Substituted values HTML-escaped; fragments sanitized  
- Template mutations audited (`notification_template.*`)  
- Delivery `status=sent` means SMTP/log **acceptance** only — `teams_delivery_confirmed` is always false in-app  
