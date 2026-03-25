"""
Database engine and session factory for Contexa.

Creates a SQLite engine targeting ~/.local/share/contexa/contexa.db.
Provides a session factory and init_db() which runs Alembic migrations
to bring the schema up to date on first run or after upgrades.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _get_alembic_cfg(db_path: Path) -> AlembicConfig:
    """Build an Alembic config pointing at the migrations directory."""
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def build_engine(data_dir: Path | None = None):
    """Create and return a SQLAlchemy engine for the local SQLite database.

    Args:
        data_dir: Directory where contexa.db will be stored.
                  Defaults to ~/.local/share/contexa/.
    """
    if data_dir is None:
        data_dir = Path("~/.local/share/contexa").expanduser()

    data_dir = Path(data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "contexa.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def build_session_factory(engine) -> sessionmaker[Session]:
    """Return a session factory bound to the given engine."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db(data_dir: Path | None = None):
    """Initialise the database by running all pending Alembic migrations.

    Safe to call on every daemon startup — Alembic is a no-op when the
    schema is already up to date.

    Args:
        data_dir: Directory where contexa.db lives.
                  Defaults to ~/.local/share/contexa/.
    """
    if data_dir is None:
        data_dir = Path("~/.local/share/contexa").expanduser()

    data_dir = Path(data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "contexa.db"
    cfg = _get_alembic_cfg(db_path)
    command.upgrade(cfg, "head")
