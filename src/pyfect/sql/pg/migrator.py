"""Migrations for PostgreSQL (Effect's ``@effect/sql-pg`` ``PgMigrator``):
``Migrator``'s runner, dumping the schema with ``pg_dump``.

``pg_dump`` connects with the client's own libpq parameters (the URL and
explicit fields, socket, user, database, ``application_name``,
``options``, TLS, connect timeout); the password goes through
``PGPASSWORD`` and nothing else of the environment but ``PATH``. A dump
that fails is logged, as for every driver.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import tempfile
from typing import Never

from psycopg.conninfo import make_conninfo

from pyfect._all import all as all_effects
from pyfect._core import Effect
from pyfect.effect import fail, gen, sync, try_
from pyfect.file_system import FileSystem
from pyfect.layer import Layer
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.path import Path
from pyfect.process import ChildProcessSpawner
from pyfect.process import make as make_command
from pyfect.scope import acquire_use_release
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.sql.migrator import (
    Loader,
    MigrationError,
    Runner,
    from_record,
    make,
)
from pyfect.sql.migrator_file_system import from_file_system
from pyfect.sql.pg._resolve import ResolvedConfig, resolve, resolve_password
from pyfect.sql.pg.client import PgClient

_COMMENT = re.compile(r"^--.*$", re.MULTILINE)
_SET = re.compile(r"^SET .*$", re.MULTILINE)
_SELECT_CATALOG = re.compile(r"^SELECT pg_catalog\..*$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{2,}")

type DumpServices = PgClient | ChildProcessSpawner | FileSystem | Path


def _clean(dump: str) -> str:
    dump = _COMMENT.sub("", dump)
    dump = _SET.sub("", dump)
    dump = _SELECT_CATALOG.sub("", dump)
    return _BLANK_LINES.sub("\n\n", dump).strip()


_SECRET_PARAMS = ("sslpassword",)
"""libpq parameters kept off ``pg_dump``'s command line, which any local
account can read; libpq reads them from a private service file instead (it
has no environment variable for them)."""

_SERVICE = "pyfect_pg_dump"


def _conninfo(resolved: ResolvedConfig) -> str:
    """The connection for ``pg_dump``'s ``--dbname``, without its secrets
    (``_secrets``), which the service named here carries."""
    params = {k: v for k, v in resolved.params.items() if k not in _SECRET_PARAMS}
    params.pop("client_encoding", None)
    if resolved.connect_timeout.is_finite():
        params["connect_timeout"] = str(max(1, math.ceil(resolved.connect_timeout.to_seconds())))
    if _secrets(resolved):
        params["service"] = _SERVICE
    return make_conninfo(**params)


def _secrets(resolved: ResolvedConfig) -> dict[str, str]:
    return {k: v for k, v in resolved.params.items() if k in _SECRET_PARAMS}


def _write_service_file(secrets: dict[str, str]) -> str:
    """A service file only this user reads (``mkstemp`` makes it 0600)."""
    for name, value in secrets.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"The libpq parameter {name} must not hold a line break")
    fd, path = tempfile.mkstemp(prefix="pyfect-pg-dump-", suffix=".conf")
    with os.fdopen(fd, "w") as file:
        file.write(f"[{_SERVICE}]\n")
        file.writelines(f"{name}={value}\n" for name, value in secrets.items())
    return path


def _remove(path: str | None) -> Effect[None]:
    def remove() -> None:
        if path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)

    return sync(remove)


def _pg_dump(
    conninfo: str, password: str | None, args: list[str], service_file: str | None = None
) -> Effect[str, Exception, ChildProcessSpawner]:
    env: dict[str, str | None] = {"PATH": os.environ.get("PATH")}
    if password is not None:
        env["PGPASSWORD"] = password
    if service_file is not None:
        env["PGSERVICEFILE"] = service_file
    command = make_command(
        "pg_dump",
        [*args, "--no-owner", "--no-privileges", "--no-password", f"--dbname={conninfo}"],
        env=env,
        extend_env=False,
    )
    return ChildProcessSpawner().flat_map(lambda spawner: spawner.string(command)).map(_clean)


def _dump_all(table: str) -> Effect[str, Exception, PgClient | ChildProcessSpawner]:
    def body():
        client = yield from PgClient()
        resolved = yield from resolve(client.config)
        password = yield from resolve_password(resolved.password)
        conninfo = _conninfo(resolved)
        secrets = _secrets(resolved)

        def dumps(service_file: str | None) -> Effect[str, Exception, ChildProcessSpawner]:
            data = ["--column-inserts", "--data-only", f"--table={table}"]
            return all_effects(
                _pg_dump(conninfo, password, ["--schema-only"], service_file),
                _pg_dump(conninfo, password, data, service_file),
                concurrency=2,
            ).map(lambda parts: parts[0] + "\n\n" + parts[1])

        if not secrets:
            return (yield from dumps(None))
        acquire: Effect[str | None, Exception] = try_(
            lambda: _write_service_file(secrets), lambda error: error
        )
        return (yield from acquire_use_release(acquire, dumps, lambda path, _: _remove(path)))

    return gen(body)


def dump_schema(path: str, table: str) -> Effect[None, MigrationError, DumpServices]:
    """Write the schema and the migrations table's rows to ``path``."""

    def body():
        fs = yield from FileSystem()
        paths = yield from Path()
        dump = yield from _dump_all(table)
        yield from fs.make_directory(paths.dirname(path), recursive=True)
        yield from fs.write_file_string(path, dump)

    def failed(error: Exception) -> Effect[Never, MigrationError]:
        message = getattr(error, "message", None) or str(error)
        return fail(MigrationError(kind="Failed", message=str(message), cause=error))

    written: Effect[None, Exception, DumpServices] = gen(body)
    return written.catch_all(failed)


run: Runner[DumpServices] = make(dump_schema)
"""Run the new migrations of ``loader`` (see ``migrator.make``); with a
``schema_directory``, dump the schema there with ``pg_dump``."""


def layer[R = Never](
    *,
    loader: Loader[R],
    schema_directory: str | None = None,
    table: str = "effect_sql_migrations",
) -> Layer[Never, MigrationError | SqlError, SqlClient | DumpServices | R]:
    """Runs the migrations when built."""
    return layer_effect_discard(run(loader=loader, schema_directory=schema_directory, table=table))


__all__ = [
    "DumpServices",
    "Loader",
    "MigrationError",
    "SqlError",
    "dump_schema",
    "from_file_system",
    "from_record",
    "layer",
    "run",
]
