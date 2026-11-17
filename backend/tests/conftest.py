import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://pantry@127.0.0.1:54329/pantry_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("CAPACITY_FRESH_HOURS", "48")

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text


@pytest.fixture(scope="session", autouse=True)
def migrated():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture()
def db():
    from app.database import SessionLocal

    session = SessionLocal()
    session.execute(
        text(
            """
            TRUNCATE TABLE
              allocation_events,
              allocations,
              idempotency_keys,
              capacity_lines,
              capacity_storage,
              capacity_reports,
              food_batches,
              site_assignments,
              sites,
              networks,
              users
            RESTART IDENTITY CASCADE
            """
        )
    )
    session.commit()
    yield session
    session.close()
