"""SQLite helpers and schema initialization for SignConnect."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


LOGGER = logging.getLogger(__name__)


@contextmanager
def get_connection(database_path: str) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row dictionary support."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(database_path: str, schema_path: str) -> None:
    """Initialize database schema and apply any pending migrations."""
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(schema_path)
    if not schema.exists():
        raise FileNotFoundError(f"Schema file not found: {schema}")

    with get_connection(str(db_path)) as connection:
        # Enable WAL mode for better concurrent read/write performance.
        connection.execute("PRAGMA journal_mode=WAL")
        script = schema.read_text(encoding="utf-8")
        connection.executescript(script)

        # ── Migrations for existing databases ──────────────────────────────
        # Add user_id column to translations if it was created before this
        # column was introduced.  The column is nullable so existing rows
        # retain their anonymous status.
        existing_cols = {
            row[1]
            for row in connection.execute("PRAGMA table_info(translations)")
        }
        if "user_id" not in existing_cols:
            connection.execute(
                "ALTER TABLE translations ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )
            LOGGER.info("Migration applied: translations.user_id column added")

    LOGGER.info("Database initialized at %s", db_path)
