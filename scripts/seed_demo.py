#!/usr/bin/env python3
"""CLI entry for seeding labeled demo data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_MODE", "local_dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/maintenancehub.db")

from maintenancehub_api.db import Base, SessionLocal, engine  # noqa: E402
from maintenancehub_api import models  # noqa: E402, F401
from maintenancehub_api.seed import DEMO_PASSWORD, seed_demo  # noqa: E402


def main() -> None:
    Path("data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo(db)
        print("Demo data ready.")
        print(f"  Login: publisher@demo.example.com / {DEMO_PASSWORD}")
        print(f"  Login: viewer@demo.example.com / {DEMO_PASSWORD}")
        print(f"  Login: admin@demo.example.com / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
