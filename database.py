import os
from sqlmodel import SQLModel, create_engine, Session

# Allow the database URL to be overridden via environment variable. When
# deploying to Render (or any cloud provider) you should provision a
# managed Postgres/MySQL instance and set the `DATABASE_URL` env var
# accordingly. For local development we fall back to a file-backed SQLite
# database so you don't need to install anything else.

# Only Turso/SQLite is supported now.  In production the only
# relevant variable is `TURSO_DATABASE_URL` (plus `TURSO_AUTH_TOKEN` when
# the database is private).  For local development we still fall back to a
# file-backed SQLite database so you don't need to install anything else.

TURSO_URL = os.getenv("TURSO_DATABASE_URL")

if TURSO_URL:
    import libsql

    # SQLAlchemy expects a DB‑API connection that behaves like the standard
    # sqlite3 module.  The libsql client lacks a couple of methods so we
    # wrap it and stub out whatever SQLAlchemy uses.
    class _SQLiteShim:
        def __init__(self, inner):
            self._inner = inner

        def create_function(self, name, num_params, fn, **kwargs):
            # Turso doesn't support user-defined functions; noop is fine.
            return None

        def __getattr__(self, attr):
            return getattr(self._inner, attr)

    def _turso_creator():
        auth = os.getenv("TURSO_AUTH_TOKEN", "")
        raw_conn = libsql.connect(TURSO_URL, auth_token=auth)
        return _SQLiteShim(raw_conn)

    engine = create_engine("sqlite://", echo=False, creator=_turso_creator)
else:
    # Development / local fallback
    sqlite_file_name = "database.db"
    sqlite_url = f"sqlite:///{sqlite_file_name}"
    connect_args = {"check_same_thread": False}
    engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)


def create_db_and_tables():
    """On startup create any tables that don't yet exist.

    In a production setting you would typically run proper migrations instead
    of calling ``create_all``.  For a small project you can live with the
    simple approach or add Alembic later.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
