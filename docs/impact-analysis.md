# M14 — Maintenance Impact Analysis & Notification Preview

## Purpose

Before publishing maintenance, publishers review **direct targets**, **suggested downstream consumers**, **notification reach**, and **advisory scheduling conflicts**. Analysis is advisory — not monitoring.

## Dependency traversal

`Dependency` edges mean **consumer → provider** (`from` depends on `to`). Impact analysis walks **reverse** edges from seed providers to find potentially affected consumers.

- Multi-hop BFS with configurable `max_depth` (default 5, max 20)
- Cycle detection; alternate path provenance preserved (deduped by dependency id sequence)
- Environment-aware edges (e.g. Claims INT → Oracle NON-PROD)
- Origins: `manual` | `import` (CMDB); imported freshness warnings after 90 days
- **No confidence percentages.** Absent edges ≠ proof of no dependency.

## APIs

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/v1/impact-analysis/preview` | Read-only preview + `revision_token` |
| `POST` | `/api/v1/impact-analysis/events/{id}/confirm` | Persist decisions; optional publish + outbox |

Confirm rejects stale tokens with **409**. Delivery/audit history is never wiped.

## Authz

Grants required on **seed** applications. Downstream includes are notification-reach suggestions only.

## Series vs occurrence

Series impacts are defaults. Occurrence overrides (including explicit empty sets) replace series for that occurrence identity. Confirmed decisions are audited in `impact_decisions` and not silently overwritten by later reanalysis.

## Demo seed

`[DEMO] Oracle Database (NON-PROD)` with consumers Claims INT, Billing DEV, Member API QA, transitive Portal BFF QA; recurring Oracle series with one occurrence override; overlapping Claims event for conflicts.
