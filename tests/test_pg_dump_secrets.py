"""``pg_dump`` gets a client-key passphrase (libpq's ``sslpassword``)
through a service file only this user reads, never on its command line,
which other local accounts see (``ps``), nor in a spawn failure."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import platform
from pyfect.sql.pg import PgConnectionConfig
from pyfect.sql.pg._resolve import resolve
from pyfect.sql.pg.migrator import (
    _conninfo,  # pyright: ignore[reportPrivateUsage]
    _dump_all,  # pyright: ignore[reportPrivateUsage]
)

SECRET = "key-passphrase-1234"
CONFIG = PgConnectionConfig(
    host="127.0.0.1",
    database="app",
    username="app",
    ssl={"sslcert": "/etc/app/client.crt", "sslkey": "/etc/app/client.key", "sslpassword": SECRET},
)


def test_the_passphrase_is_not_in_the_conninfo() -> None:
    resolved = fx.run_blocking(resolve(CONFIG).or_die())
    conninfo = _conninfo(resolved)
    assert SECRET not in conninfo
    assert "service=" in conninfo


def test_pg_dump_reads_the_passphrase_from_a_private_service_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record"
    stub = tmp_path / "pg_dump"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" >> "{record}"\n'
        f'/usr/bin/stat -f %Lp "$PGSERVICEFILE" >> "{record}" 2>/dev/null '
        f'|| /usr/bin/stat -c %a "$PGSERVICEFILE" >> "{record}"\n'
        f'/bin/cat "$PGSERVICEFILE" >> "{record}"\n'
        f'printf "file:%s\n" "$PGSERVICEFILE" >> "{record}"\n'
    )
    stub.chmod(stat.S_IRWXU)
    monkeypatch.setenv("PATH", str(tmp_path))

    class _Client:
        config = CONFIG

    from pyfect.sql.pg.client import PgClient

    program: Any = (
        _dump_all("migrations")
        .pipe(fx.provide_service(PgClient, _Client()))  # pyright: ignore[reportArgumentType]
        .pipe(fx.provide(platform.layer))
    )
    fx.run_blocking(fx.scoped(program))
    lines = record.read_text().splitlines()
    argv = [line for line in lines if line.startswith("--")]
    assert argv
    assert not any(SECRET in arg for arg in argv)
    assert "600" in lines
    assert f"sslpassword={SECRET}" in lines
    # The service file is gone once the dumps are done.
    [service] = {line.removeprefix("file:") for line in lines if line.startswith("file:")}
    assert service.endswith(".conf")
    assert not os.path.exists(service)
