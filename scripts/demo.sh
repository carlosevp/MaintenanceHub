#!/usr/bin/env bash
# Zero-config local demo (M17). Defaults to Essentials.
# Never enables silent demo auth in deployed enterprise.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Default Essentials — Team/Enterprise must be explicit (no silent Enterprise).
PROFILE="${EXPERIENCE_PROFILE:-essentials}"
DB_URL="${DATABASE_URL:-sqlite:///./data/maintenancehub.db}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

case "$PROFILE" in
  essentials|team|enterprise) ;;
  *)
    echo "ERROR: Unknown EXPERIENCE_PROFILE=$PROFILE (valid: essentials|team|enterprise)." >&2
    exit 1
    ;;
esac

if [[ "${ENVIRONMENT:-development}" == "staging" || "${ENVIRONMENT:-development}" == "production" ]]; then
  echo "ERROR: make demo refuses to run when ENVIRONMENT is staging or production." >&2
  echo "Local demo auth must never be silent in deployed enterprise." >&2
  exit 1
fi

mkdir -p data data/notification-capture docs/artifacts/m17
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip -q
pip install -e "apps/api[dev]" -q
pip install -e apps/worker -q
(cd apps/web && npm install --silent)

export ENVIRONMENT=development
export AUTH_MODE=local_dev
export SEED_DEMO_DATA=true
export DATABASE_URL="$DB_URL"
export EXPERIENCE_PROFILE="$PROFILE"
export SMTP_ENABLED=false
export SERVICENOW_ENABLED=false
export JWT_SECRET="${JWT_SECRET:-change-me-local-dev-only}"
export PUBLIC_BASE_URL="http://127.0.0.1:${API_PORT}"
export MH_NOTIFICATION_CAPTURE_DIR="$ROOT/data/notification-capture"

echo "==> Migrating ($DB_URL)"
alembic -c db/alembic.ini upgrade head

echo "==> Starting API on :${API_PORT} (profile=$PROFILE)"
uvicorn maintenancehub_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port "$API_PORT" \
  >data/demo-api.log 2>&1 &
echo $! >data/demo-api.pid

echo "==> Starting worker (notification capture → data/notification-capture/)"
PYTHONPATH=apps/api/src:apps/worker/src python -m maintenancehub_worker.main \
  >data/demo-worker.log 2>&1 &
echo $! >data/demo-worker.pid

echo "==> Starting web on :${WEB_PORT}"
(cd apps/web && npm run dev -- --host 127.0.0.1 --port "$WEB_PORT") \
  >data/demo-web.log 2>&1 &
echo $! >data/demo-web.pid

sleep 3
cat <<EOF

MaintenanceHub demo is up

  Profile: $PROFILE
  Web:     http://127.0.0.1:${WEB_PORT}
  API:     http://127.0.0.1:${API_PORT}/docs
  Notify:  captured under data/notification-capture/ (SMTP off; no SN/AD required)

Demo credentials (local_dev only — refused in staging/production):
  viewer@demo.example.com     / password123
  publisher@demo.example.com  / password123
  admin@demo.example.com      / password123

Stories (UI selector — presentation only; cannot unlock APIs):
  1) Essentials · Claims INT
  2) Team · Weekly Payments     → make demo-team
  3) Advanced · Oracle NON-PROD → make demo-team  (impact analysis)

Other profiles:
  make demo              # Essentials (default)
  make demo-team         # Team
  make demo-enterprise   # Enterprise
  make demo-stop

EOF
