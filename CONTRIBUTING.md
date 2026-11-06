# Contributing to MaintenanceHub

## Branching

- **Default base:** `main`
- Open **one focused PR per change** (feature, fix, or docs). Avoid long stacked feature branches.
- Prefer short-lived branches named for the change (e.g. `cursor/<short-description>`).

## Before opening a PR

1. Run locally:
   ```bash
   make lint
   make test
   make web-test
   cd apps/web && npm run build
   ```
2. Prefer Postgres when exercising leases/concurrency (`TEST_POSTGRES_URL` or Compose).
3. Do not commit secrets, `.env` files with credentials, or service client secrets.
4. Update `docs/LIMITATIONS.md` / `docs/IMPLEMENTATION_AUDIT.md` when behavior or gaps change.

## Local development

Exact quick-start commands live in [README.md](README.md). Short form:

```bash
make install && make migrate
make api      # terminal 1
make worker   # terminal 2
make web      # terminal 3
```

Or integrated: `make compose-up` → http://localhost:8080

## Scope reminders

- This is a **communication** platform, not monitoring.
- No Graph/Teams APIs (Teams via email bridge only).
- Confirmed communication ≠ approved window alone.
