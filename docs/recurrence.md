# Recurrence (M3b)

## Storage

- One master `maintenance_events` row per series (`is_recurring=true`) — series = RRULE + defaults
- `recurrence_rules.rrule` (RFC5545 body) + optional `until_at`
- `recurrence_exceptions` keyed by **`original_starts_at`** (`cancel` | `reschedule`)
- Sparse `occurrence_records` (+ optional `occurrence_impacts`) only when there is lifecycle state, overrides, or audit — **never** unbounded materialization
- Impact resolution: series `event_impacts` defaults, replaced by occurrence impacts when `impacts_overridden`

## Identity

Stable occurrence id = `{series_id}@{original_starts_at as YYYYMMDDTHHMMSSZ}`.

Rescheduling an occurrence keeps the same logical id; only effective `starts_at`/`ends_at` change. Calendar rows, reminder keys, and ICS `RECURRENCE-ID` all use that original start.

ICS: master `UID={series_id}@maintenancehub` + `RRULE` + `EXDATE` for cancels; overrides are extra `VEVENT`s with the same `UID` and `RECURRENCE-ID`.

## Occurrence lifecycle

Per occurrence (not series-wide unless explicitly cancelling/editing the series):

`scheduled` → `in_progress` → `extended` → `verifying` → `completed` | `cancelled`

- Approved windows ≠ confirmed outages; clock time never auto-completes
- Invalid transitions return **409**
- Application-scoped grants required on impacted apps
- APIs: `POST …/occurrences/transition|extend|cancel`, `PATCH …/occurrences`, `GET …/occurrences`, `GET …/occurrences/history`
- Overrides: expected/actual start/end, expected impact, description, affected apps/envs
- Parent RRULE changes do **not** overwrite historical occurrence records

## Communication phases (human-published only)

| Phase | Meaning |
|-------|---------|
| `approved_window` | Window approved; **not** confirmed for broad communication |
| `scheduled` | Confirmed, not yet executing |
| `executing` | Human transitioned to `in_progress` / `extended` / `verifying` (per occurrence when recorded) |
| `completed` / `cancelled` | Terminal |

Dashboard **current** = executing + in window. **Outages** = confirmed manual outage that is executing in window. Approved-only series never appear as current/outage and do not enqueue reminders.

## Series edit scopes

| Scope | Behavior |
|-------|----------|
| `this` | Exception on one occurrence; history otherwise unchanged |
| `this_and_future` | Truncate old series `UNTIL` before the split; create a **new** master from that point. Historical exceptions/reminders/deliveries/audit on the old master are preserved. Future exceptions after the cut stay stored on the old rule but no longer expand. |
| `all` | Update master fields/RRULE. **Exception reconciliation** runs first: preserve historical executed + compatible overrides; incompatible future exceptions require `exception_reconcile=drop_incompatible_future` or explicit `drop_exception_originals`. Execution/notification audit is never silently discarded. |

## Reminders / lifecycle notifications

- Horizon: next 45 days only
- Job key: `reminder:event:{id}:orig:{original}:sub:{sub}:offset:{n}`
- Lifecycle delivery key includes `orig:{original}` so two occurrences of the same series notify independently
- Cancelled / completed occurrences → queued reminder jobs marked `dead`; already-sent deliveries are immutable
- Reschedule updates pending reminder `run_at` without duplicating keys
- Concurrent workers cannot double-claim (unique idempotency + lease)
