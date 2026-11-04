"""Worker stub (M5 will implement lease loop).

Until M5, this process logs that jobs exist and exits cleanly when idle.
It does not claim or execute notification deliveries.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("maintenancehub.worker")

# Import API models/session
ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "api" / "src"
sys.path.insert(0, str(API_SRC))


def main() -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./data/maintenancehub.db")
    if db_url.startswith("sqlite"):
        logger.warning(
            "SQLite profile: run a single worker only (see docs/LIMITATIONS.md). "
            "Job claim/lease loop is stubbed until M5."
        )

    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args, future=True)
    Session = sessionmaker(bind=engine, future=True)

    poll = float(os.environ.get("WORKER_POLL_SECONDS", "10"))
    logger.info("Worker stub started (M5 incomplete). Polling every %ss", poll)

    while True:
        try:
            with Session() as db:
                try:
                    row = db.execute(
                        text("SELECT COUNT(*) FROM jobs WHERE status = 'queued'")
                    ).scalar()
                    logger.info("Queued jobs: %s (not processing until M5)", row)
                except Exception as exc:  # noqa: BLE001
                    logger.info("Jobs table not ready yet: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Worker loop error: %s", exc)
        time.sleep(poll)


if __name__ == "__main__":
    main()
