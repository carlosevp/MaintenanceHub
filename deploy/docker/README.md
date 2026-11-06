# Docker images

Non-root Dockerfiles live next to each app (UID `10001`):

| Image | Dockerfile |
|-------|------------|
| API | `apps/api/Dockerfile` |
| Worker | `apps/worker/Dockerfile` |
| Web | `apps/web/Dockerfile` |

```bash
# from repo root
docker build -f apps/api/Dockerfile -t maintenancehub-api:local .
docker build -f apps/worker/Dockerfile -t maintenancehub-worker:local .
docker build -f apps/web/Dockerfile -t maintenancehub-web:local .

# or
docker compose up --build
```

SQLite compose profile: run **one** worker replica only. For multi-worker / multi-api, use Postgres (`docker compose --profile postgres`).
