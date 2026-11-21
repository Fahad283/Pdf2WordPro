from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    # Store UTC as a naive database timestamp on both supported dialects.
    return datetime.now(UTC).replace(tzinfo=None)


def make_engine(url: str) -> Engine:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = make_url(url)
    options = {}
    if parsed.get_backend_name() == "postgresql":
        options["connect_args"] = {"connect_timeout": 5}
    if parsed.get_backend_name() == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        options["connect_args"] = {"check_same_thread": False, "timeout": 15}
    database = create_engine(parsed, pool_pre_ping=True, **options)
    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(database, "connect")
        def sqlite_pragma(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return database


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
