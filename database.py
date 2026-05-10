"""
database.py — SQLAlchemy connection layer for MakerSpaceHub.

Owns the engine, session factory, declarative Base, and the FastAPI
dependency that yields a session per request.

Replaces the role that storage.py played for JSON-file persistence.
"""
import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load .env on import so DATABASE_URL is available when the engine is built.
# os.environ[KEY] raises KeyError if missing — fail fast, since the app
# can't run without a database URL.
load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]


# The Engine is the entry point to the database. It manages the connection
# pool — creating it once at module level (not per-request) means SQLAlchemy
# can reuse connections rather than dialing up a new one for every query.
#
# echo=False means SQL queries aren't printed to stdout. Flip to True when
# you want to see exactly what SQL SQLAlchemy is generating — useful for
# debugging or for the validation report screenshots.
engine = create_engine(DATABASE_URL, echo=False)


# A session factory. Calling SessionLocal() returns a fresh Session bound
# to the engine. We do this per-request rather than sharing one session
# globally — sessions hold per-transaction state, so a long-lived shared
# session would cause stale-data and locking issues.
#
# autocommit=False — we control when transactions commit (default).
# autoflush=False  — SQLAlchemy doesn't auto-push pending changes on every
#                    read query. More predictable; flushes happen on commit().
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# Declarative Base — every ORM model class will inherit from this.
# SQLAlchemy collects model definitions on Base.metadata, which lets us
# later call Base.metadata.create_all(engine) to create every table at once.
class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Used like:
        @app.get("/equipment")
        def list_equipment(db: Session = Depends(get_db)):
            ...

    The session is created when the request starts, available throughout
    the request handler, and closed when the request finishes — even if
    the handler raises an exception (the finally block guarantees cleanup).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
