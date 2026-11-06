"""A PostgreSQL server for the adapter tests: `ENV_STORE_TEST_POSTGRES_URL` or a throwaway cluster.

Without the environment variable, `initdb` / `pg_ctl` from `PATH` start a private cluster: trust
authentication, `--no-locale`, no TCP listener, a unix socket in a fresh short directory under
`/tmp` (socket paths are limited to about 100 bytes) and a random port, so parallel test runs on
one machine never meet. Every test gets its own database from it.
"""

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

__all__ = ["ENV_URL", "PostgresServer", "start_server", "unique_name"]

ENV_URL: Final = "ENV_STORE_TEST_POSTGRES_URL"
_HINT: Final = (
    f"the PostgreSQL adapter tests need a server: set {ENV_URL} to a superuser URL of a "
    "throwaway server, or put initdb and pg_ctl (PostgreSQL >= 13) on PATH, e.g. "
    "'brew install postgresql@16' or 'apt install postgresql'"
)
_SUPERUSER: Final = "postgres"


def unique_name(prefix: str) -> str:
    """A fresh database, schema or role name: `prefix` and 12 random hex digits."""
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresServer:
    """A running server and how to reach it as superuser.

    Attributes:
        admin_url: Superuser URL of the maintenance database.
    """

    admin_url: str = field(repr=False)

    def url(
        self,
        database: str,
        *,
        schema: str | None = None,
        user: str | None = None,
        password: str | None = None,
        query: str | None = None,
    ) -> str:
        """URL of `database`, optionally as another role, with `?schema=` and raw query items."""
        parts = urlsplit(self.admin_url)
        netloc = parts.netloc
        if user is not None:
            credentials = quote(user, safe="")
            if password is not None:
                credentials += ":" + quote(password, safe="")
            netloc = f"{credentials}@{netloc.rpartition('@')[2]}"
        items = [item for item in (parts.query, query) if item]
        if schema is not None:
            items.append(f"schema={schema}")
        return urlunsplit((parts.scheme, netloc, "/" + quote(database), "&".join(items), ""))

    def execute(self, database: str, *statements: sql.Composed | sql.SQL) -> None:
        """Run statements as superuser in `database`, each committed on its own."""
        with psycopg.connect(self.url(database), autocommit=True) as connection:
            for statement in statements:
                connection.execute(statement)

    def query(self, database: str, statement: sql.Composed | sql.SQL) -> list[tuple[object, ...]]:
        """Fetch all rows of a query, as superuser."""
        with psycopg.connect(self.url(database), autocommit=True) as connection:
            return list(connection.execute(statement).fetchall())

    @contextmanager
    def database(self, *, icu_locale: str | None = None) -> Generator[str]:
        """A fresh, empty database, dropped (with its connections) afterwards.

        `icu_locale` gives the database a linguistic default collation instead of the server's.
        """
        name = unique_name("es_test")
        maintenance = self._maintenance_database()
        create = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        if icu_locale is not None:
            create += sql.SQL(
                " TEMPLATE template0 LOCALE_PROVIDER icu ICU_LOCALE {} LOCALE 'C'"
            ).format(sql.Literal(icu_locale))
        self.execute(maintenance, create)
        try:
            yield name
        finally:
            self.execute(
                maintenance,
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)),
            )

    @contextmanager
    def role(self) -> Generator[tuple[str, str]]:
        """A login role without any privileges; dropped afterwards (drop its databases first)."""
        name = unique_name("es_role")
        password = secrets.token_hex(12)
        maintenance = self._maintenance_database()
        self.execute(
            maintenance,
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(name), sql.Literal(password)
            ),
        )
        try:
            yield name, password
        finally:
            self.execute(
                maintenance, sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name))
            )

    def _maintenance_database(self) -> str:
        return urlsplit(self.admin_url).path.lstrip("/") or _SUPERUSER


def _run(*command: str) -> None:
    # macOS: the postmaster refuses to start without a valid locale in the environment.
    environment = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    subprocess.run(  # noqa: S603 - fixed arguments, binaries resolved from PATH
        command, check=True, capture_output=True, env=environment
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@contextmanager
def _temporary_cluster() -> Generator[PostgresServer]:
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if initdb is None or pg_ctl is None:
        pytest.fail(_HINT, pytrace=False)
    short_root = "/tmp" if Path("/tmp").is_dir() else None  # noqa: S108 - unique mkdtemp below
    directory = Path(tempfile.mkdtemp(prefix="es-pg-", dir=short_root))
    data = directory / "data"
    port = _free_port()
    try:
        _run(initdb, "-D", str(data), "-A", "trust", "-U", _SUPERUSER, "--no-locale", "-E", "UTF8")
        options = f"-k {directory} -p {port} -c listen_addresses='' -c max_connections=200"
        _run(pg_ctl, "-D", str(data), "-o", options, "-l", str(directory / "log"), "-w", "start")
        try:
            host = quote(str(directory), safe="")
            yield PostgresServer(
                admin_url=f"postgresql://{_SUPERUSER}@/{_SUPERUSER}?host={host}&port={port}"
            )
        finally:
            _run(pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop")
    except subprocess.CalledProcessError as err:
        log = directory / "log"
        details = log.read_text(encoding="utf-8") if log.exists() else err.stderr
        pytest.fail(f"{_HINT}\nstarting a temporary cluster failed:\n{details}", pytrace=False)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@contextmanager
def start_server() -> Generator[PostgresServer]:
    """The server from `ENV_STORE_TEST_POSTGRES_URL`, else a temporary cluster."""
    url = os.environ.get(ENV_URL)
    if url:
        yield PostgresServer(admin_url=url)
        return
    with _temporary_cluster() as server:
        yield server
