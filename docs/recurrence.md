# Recurrence (M3b)

## Storage

- One master `maintenance_events` row per series (`is_recurring=true`)
- `recurrence_rules.rrule` (RFC5545 body) + optional `until_at`
- `recurrence_exceptions` keyed by **`original_starts_at`** (`cancel` | `reschedule`)
- Occurrences are **never** unbounded-materialized in the DB

## Identity

Stable occurrence id = `{series_id}@{original_starts_at as YYYYMMDDTHHMMSSZ}`.

Rescheduling an occurrence keeps the same logical id; only effective `starts_at`/`ends_at` change. Calendar rows, reminder keys, and ICS `RECURRENCE-ID` all use that original start.

ICS: master `UID={series_id}@maintenancehub` + `RRULE` + `EXDATE` for cancels; overrides are extra `VEVENT`s with the same `UID` and `RECURRENCE-ID`.

## Communication phases (human-published only)

| Phase | Meaning |
|-------|---------|
| `approved_window` | Window approved; **not** confirmed for broad communication |
| `scheduled` | Confirmed, not yet executing |
| `executing` | Human transitioned to `in_progress` / `extended` / `verifying` |
| `completed` / `cancelled` | Terminal |

Dashboard **current** = executing + in window. **Outages** = confirmed manual outage that is executing in window. Approved-only series never appear as current/outage and do not enqueue reminders.

## Series edit scopes

| Scope | Behavior |
|-------|----------|
| `this` | Exception on one occurrence; history otherwise unchanged |
| `this_and_future` | Truncate old series `UNTIL` before the split; create a **new** master from that point. Historical exceptions/reminders/deliveries/audit on the old master are preserved. Future exceptions after the cut stay stored on the old rule but no longer expand. |
| `all` | Update master fields/RRULE. **Existing exceptions are retained** by `original_starts_at`. If DTSTART/pattern changes so those originals no longer land on generated slots, exceptions remain for audit but may stop matching — clear them explicitly if needed. |

## Reminders

- Horizon: next 45 days only
- Job key: `reminder:event:{id}:orig:{original}:sub:{sub}:offset:{n}`
- Delivery key includes the same original occurrence stamp
- Cancelled occurrences → queued jobs marked `dead`; already-sent deliveries are not resent
- Concurrent schedule runs are idempotent (unique constraint + savepoint insert)
