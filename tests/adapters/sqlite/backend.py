"""A contract `Backend` on a temporary SQLite file, shared by the SQLite adapter tests."""

import sqlite3
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from environment_store.adapters.sqlite import SqliteAdapter, open_sqlite
from environment_store.core.adapter import SetupMode

__all__ = ["SqliteBackend", "meta_rows", "raw", "snapshot", "sqlite_backend", "tables", "url_of"]


def url_of(path: Path) -> str:
    """The connection string of an absolute database path."""
    return f"sqlite:///{path}"


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteBackend:
    """One database file; every `open()` is a new connection."""

    path: Path

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> SqliteAdapter:
        return open_sqlite(url_of(self.path), setup=setup)


@contextmanager
def sqlite_backend(base: Path) -> Generator[SqliteBackend]:
    """A fresh backend in its own directory below `base`, removed on exit."""
    with tempfile.TemporaryDirectory(dir=base) as directory:
        yield SqliteBackend(path=Path(directory) / "envs.db")


@contextmanager
def raw(path: Path) -> Generator[sqlite3.Connection]:
    """A plain autocommit connection to the file, bypassing the adapter; closed on exit."""
    connection = sqlite3.connect(path, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


def snapshot(path: Path) -> tuple[str, list[str]]:
    """The journal mode and the full SQL dump of a file, to prove nothing was changed."""
    with raw(path) as connection:
        (mode,) = connection.execute("PRAGMA journal_mode").fetchone()
        return mode, list(connection.iterdump())


def meta_rows(path: Path) -> dict[str, str]:
    with raw(path) as connection:
        return dict(connection.execute("SELECT key, value FROM meta").fetchall())


def tables(path: Path) -> set[str]:
    with raw(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    return {name for (name,) in rows}
