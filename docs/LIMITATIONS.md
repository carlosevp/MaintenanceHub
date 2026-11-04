# Limitations & incomplete capabilities

This document lists what is **explicitly incomplete or deferred**. Nothing listed here is “fake finished.”

## Current wave (through M8)

| Item | Status |
|------|--------|
| **M3b Recurrence** | Schema exists; RRULE is emitted in ICS when present, but **occurrence expansion / DST fixtures for in-app calendar are incomplete**. |
| **M5 Durable jobs** | **Implemented**: outbox drain → leased jobs → handlers; SQLite single-worker; Postgres SKIP LOCKED path. Digests as job type not fully wired. |
| **M6 Subscriptions + SMTP** | **Implemented**: subscriptions, reminders, templates, log/SMTP sink, delivery history, dedupe. Optional digests are schema-only (`digest_mode`); digest worker not shipped. |
| **M7 Power Automate bridge** | **Implemented**: `teams_bridge_channel` destinations, subject routing template, connection test. No Teams SDK. |
| **M8 ICS feeds** | **Implemented**: revocable tokens, favorites/subscriptions scope, Outlook-oriented VCALENDAR. Full VTIMEZONE blocks / complex EXDATE suites are minimal (UTC DTSTART/DTEND + TZ hint). |
| **ServiceNow poll / CMDB CSV** | Not implemented (M9–M10). |
| **Enterprise OIDC/LDAP** | Provider hooks via `AUTH_MODE`; only `local_dev` login works. Fail-closed startup guard is implemented. |
| **Banner package** | Stub under `packages/banner` (M12). |
| **OpenShift manifests** | Minimal placeholders under `deploy/openshift/`. |
| **Application-scoped grants enforcement** | Grants table exists; full grant checks → M11. |

## Permanent non-goals

- Application/infra health monitoring, synthetics, metrics, auto-status from telemetry
- Direct Microsoft Teams API / webhooks (**Teams via email bridge only**)
- `/healthz` and `/readyz` are **platform probes for MaintenanceHub pods only**

## SQLite local profile

Run **one worker** only. Multi-replica lease safety (`FOR UPDATE SKIP LOCKED`) requires Postgres.
