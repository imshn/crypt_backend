import os
from sqlmodel import SQLModel, create_engine, Session

# Allow the database URL to be overridden via environment variable. When
# deploying to Render (or any cloud provider) you should provision a
# managed Postgres/MySQL instance and set the `DATABASE_URL` env var
# accordingly. For local development we fall back to a file-backed SQLite
# database so you don't need to install anything else.

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # SQLAlchemy 2.0 prefers the `postgresql://` scheme; some providers
    # (Heroku, Render) still hand out URLs with `postgres://`.  Rewrite
    # it here to avoid the warning.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Expect a full SQLAlchemy URL, e.g.:
    #   postgresql://user:password@hostname:5432/dbname
    # Render will automatically set this when you add a Postgres database
    # via the dashboard. Don't enable echo in production.
    engine = create_engine(DATABASE_URL, echo=False)
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
