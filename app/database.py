from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    """Declarative base for all application models."""


def make_engine(settings: Settings):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30}
        if settings.database_url.startswith("sqlite")
        else {},
    )
    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)
