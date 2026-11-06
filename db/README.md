# Database migrations

Alembic migrations are designed to be portable across **SQLite** (local) and **PostgreSQL** (deploy).

## Commands

From repo root (with API package installed and `DATABASE_URL` set):

```bash
export DATABASE_URL=sqlite:///./data/maintenancehub.db
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini downgrade -1
```

Postgres:

```bash
export DATABASE_URL=postgresql+psycopg://mh:mh@localhost:5432/maintenancehub
alembic -c db/alembic.ini upgrade head
```

## Notes

- Avoid Postgres-only types; use SQLAlchemy `JSON` (maps to JSON/JSONB).
- Timestamps are timezone-aware UTC.
- SQLite local profile: run a **single** worker process (lease locking without `SKIP LOCKED`).
