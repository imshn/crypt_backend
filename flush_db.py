import argparse
import os
from pathlib import Path

def _load_env_file(file_path: Path) -> None:
    if not file_path.exists():
        return

    for raw_line in file_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_env() -> None:
    base_dir = Path(__file__).parent
    _load_env_file(base_dir / ".env.local")
    _load_env_file(base_dir / ".env")


def _normalized_turso_url() -> str:
    raw = os.getenv("TURSO_DATABASE_URL", "")
    return raw.strip().strip('"').strip("'")


def flush_database(allow_sqlite: bool = False) -> None:
    _load_env()

    turso_url = _normalized_turso_url()
    using_turso = turso_url.startswith("libsql://")

    if not using_turso and not allow_sqlite:
        raise RuntimeError(
            "TURSO_DATABASE_URL is not set. Refusing to flush local SQLite by accident. "
            "Set TURSO_DATABASE_URL in .env.local or run with --allow-sqlite."
        )

    # Import after env loading so database engine is created for the intended target.
    from database import engine, SQLModel
    import models  # noqa: F401 - ensures metadata includes all tables

    target = turso_url if using_turso else "sqlite:///database.db"
    print(f"Target database: {target}")
    print("Dropping all tables...")
    SQLModel.metadata.drop_all(engine)
    print("Creating all tables...")
    SQLModel.metadata.create_all(engine)
    print("Database flushed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flush all tables and recreate schema")
    parser.add_argument(
        "--allow-sqlite",
        action="store_true",
        help="Allow flushing local SQLite when TURSO_DATABASE_URL is missing",
    )
    args = parser.parse_args()
    flush_database(allow_sqlite=args.allow_sqlite)
