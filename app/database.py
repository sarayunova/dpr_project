"""Database engine/session setup.

Postgres from the start, per docs/05_architecture.md and
docs/07_non_functional_requirements.md (chosen over SQLite given the
confirmed future shared-server rollout and multi-user auth requirement).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://dpr_monitor:dpr_monitor@localhost:5432/dpr_monitor",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables that don't exist yet. Local-dev convenience —
    real deployments should use `alembic upgrade head` instead (see
    alembic/)."""
    import app.models  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop and recreate every table. Local-dev only — never call this
    against a database with real data."""
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
