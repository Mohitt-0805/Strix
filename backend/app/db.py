"""SQLAlchemy 2.0 SQLite engine, session factory, and health helpers."""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_db_engine(db_path: Path) -> Engine:
    """Create a SQLite engine with foreign keys and WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory bound to the given engine."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create schema tables, append-only audit triggers, and verify connectivity."""
    import backend.app.models  # noqa: F401  # Register ORM models with Base.metadata

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
                BEFORE UPDATE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is forbidden');
                END;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
                BEFORE DELETE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is forbidden');
                END;
                """
            )
        )
        conn.execute(text("SELECT 1"))


def check_db(engine: Engine) -> bool:
    """Return True if the database responds to a simple query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
