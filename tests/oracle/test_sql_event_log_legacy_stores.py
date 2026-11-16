"""Stores the SQL encrypted event log server named ``publicKey/storeId`` up
to 0.6.5, which another (public key, store id) pair may share: only the
identity the session auth bindings show wrote them gets them, by itself
when nothing else is possible and through the operator otherwise; a
refusal clears once the store is migrated, is logged and reaches the
client; and the stores waiting for a migration can be listed. On SQLite,
PostgreSQL, MySQL and SQL Server (each server skipped without one).

0.6.5 is simulated by naming tables with the legacy key, as 0.6.5 did.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import logger
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._sql_server_encrypted import legacy
from pyfect.eventlog.event_journal import Entry, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EventLogEncryption, layer_subtle
from pyfect.eventlog.event_log_remote import (
    EventLogRemoteClient,
    EventLogRemoteService,
    make_encrypted,
)
from pyfect.eventlog.sql_event_log_server_encrypted import (
    LegacyStore,
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
)
from pyfect.redacted import make as redacted
from pyfect.rpc import test as rpc_test
from pyfect.schema import new
from pyfect.scope import Scope
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

OWNER = ("Kq9/xT2+bQ==", "main")
"""A base64 public key with a ``/``, which wrote its store under 0.6.5."""
OTHER = ("Kq9", "xT2+bQ==/main")
"""Another split of the owner's legacy key ``Kq9/xT2+bQ==/main``."""

_namespaces = itertools.count()


class _Db:
    """One database, with tables of their own under a fresh prefix."""

    def __init__(self, client: Callable[[], fx.Layer[SqlClient, Any]]) -> None:
        self.client = client
        namespace = f"legacy_{os.getpid()}_{next(_namespaces)}"
        self.prefix = f"{namespace}_events"
        self.remote_id_table = f"{namespace}_remote_id"

    def storage(self) -> fx.Layer[Server.Storage, Any]:
        return (
            SqlServer.layer_storage(
                entry_table_prefix=self.prefix, remote_id_table=self.remote_id_table
            )
            .pipe(fx.layer.provide(self.client()))
            .pipe(fx.layer.provide(digest.layer_web_crypto))
        )

    def tool[A, E](self, effect: fx.Effect[A, E, SqlClient | digest.Digest]) -> fx.Exit[A, E]:
        """Runs an operator call, outside any server."""
        return fx.run_blocking(
            effect.pipe(fx.provide(digest.layer_web_crypto)).pipe(fx.provide(self.client())).exit()
        )

    def migrate(
        self, pair: tuple[str, str], not_written_by: Sequence[str] = ()
    ) -> fx.Exit[bool, Any]:
        return self.tool(
            SqlServer.migrate_legacy_store(
                *pair,
                not_written_by=not_written_by,
                entry_table_prefix=self.prefix,
                remote_id_table=self.remote_id_table,
            )
        )

    def report(self, store_ids: Sequence[str]) -> list[LegacyStore]:
        found = self.tool(
            SqlServer.legacy_stores(
                store_ids, entry_table_prefix=self.prefix, remote_id_table=self.remote_id_table
            )
        )
        assert isinstance(found, fx.Success)
        return found.value

    def run[A](self, body: Callable[[], Generator[Any, Any, A]]) -> fx.Exit[A, Any]:
        """``body`` with one storage, as one server process."""
        return fx.run_blocking(fx.scoped(fx.gen(body)).pipe(fx.provide(self.storage())).exit())

    def bind(self, public_key: str) -> None:
        """Authenticates ``public_key`` once, as a server does."""

        def body():
            storage = yield from Server.Storage()
            yield from storage.get_or_create_session_auth_binding(public_key, bytes(32))

        assert isinstance(self.run(body), fx.Success)

    def write(self, pair: tuple[str, str], tag: str) -> None:
        def body():
            storage = yield from Server.Storage()
            yield from storage.write(pair[0], StoreId(pair[1]), [_batch(tag)])

        assert isinstance(self.run(body), fx.Success)

    def read(self, pair: tuple[str, str]) -> list[str]:
        """The tags of the pair's batches; raises the store's refusal."""
        found = self.run(lambda: _read(pair))
        if isinstance(found, fx.Failure):
            raise found.cause.squash()  # pyright: ignore[reportGeneralTypeIssues]
        return found.value


def _batch(tag: str) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=(J.make_entry_id_unsafe(),), iv=bytes(12), encrypted_batch=tag.encode()
    )


def _read(pair: tuple[str, str]) -> Generator[Any, Any, list[str]]:
    storage = yield from Server.Storage()
    latest = yield from storage.latest_sequence(pair[0], StoreId(pair[1]))
    if latest is None:
        return []
    batches = yield from storage.changes(pair[0], StoreId(pair[1]), 1).take(latest).run_collect()
    return [b.encrypted_batch.decode() for b in batches]


@pytest.fixture(params=["SQLite", "pg", "mysql2", "mssql"])
def db(request: pytest.FixtureRequest, tmp_path: Path) -> _Db:
    """A database: a SQLite file, or the session's PostgreSQL server or its
    MySQL or SQL Server container (skipped without one)."""
    match request.param:
        case "SQLite":
            path = str(tmp_path / "log.db")
            return _Db(lambda: sqlite.layer(sqlite.SqliteClientConfig(filename=path)))
        case "pg":
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            from ._postgres import PgServer

            server: PgServer = request.getfixturevalue("pg_server")
            return _Db(lambda: pg.layer(pg.PgPoolConfig(url=server.url)))
        case "mssql":
            pytest.importorskip("pytds")
            from pyfect.sql import mssql

            from ._mssql import MssqlServer

            mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
            return _Db(lambda: mssql.layer(mssql_server.config()))
        case _:
            pytest.importorskip("asyncmy")
            from pyfect.sql import mysql

            from ._mysql import MysqlServer

            mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
            return _Db(lambda: mysql.layer(mysql.MysqlClientConfig(url=mysql_server.url)))


class _As065:
    """A context in which the storage names tables as 0.6.5 did."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def __enter__(self) -> None:
        self._monkeypatch.setattr(legacy, "scope_key", legacy.legacy_key)

    def __exit__(self, *_: object) -> None:
        self._monkeypatch.undo()


@pytest.fixture
def as_065(monkeypatch: pytest.MonkeyPatch) -> Callable[[], _As065]:
    return lambda: _As065(monkeypatch)


def _refusal(db: _Db, pair: tuple[str, str]) -> LegacyStoreNeedsMigration:
    with pytest.raises(LegacyStoreNeedsMigration) as raised:
        db.read(pair)
    return raised.value


def _migration_refused(found: fx.Exit[bool, Any]) -> str:
    assert isinstance(found, fx.Failure)
    error = found.cause.squash()
    assert isinstance(error, LegacyStoreMigrationError)
    return error.message


# --- who gets the legacy tables ----------------------------------------------


def test_the_one_authenticated_identity_gets_its_store_with_no_operator_step(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []
    assert db.migrate(OWNER) == fx.Success(True)  # already done; a no-op
    assert db.report([OWNER[1]]) == [LegacyStore(*OWNER, "migrated")]


def test_a_key_that_never_authenticated_cannot_take_another_identitys_store(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    refusal = _refusal(db, OTHER)
    # Worded around the asking pair, without telling the operator to migrate it.
    assert refusal.message.startswith(f"Store {OTHER[1]!r} of {OTHER[0]!r} does not open")
    assert "never authenticated" in refusal.message
    assert "Do not migrate them to it" in refusal.message
    assert "never authenticated" in _migration_refused(db.migrate(OTHER))
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []


def test_a_store_two_authenticated_identities_could_have_written_waits_for_the_operator(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    db.bind(OTHER[0])  # anyone may authenticate as the other split's key
    for pair, other in [(OWNER, OTHER), (OTHER, OWNER)]:
        refusal = _refusal(db, pair)
        assert refusal.authenticated
        assert refusal.other_keys == (other[0],)
    assert db.report([OWNER[1], OTHER[1]]) == [
        LegacyStore(*OTHER, "ambiguous", (OWNER[0],)),
        LegacyStore(*OWNER, "ambiguous", (OTHER[0],)),
    ]
    # The operator must name the other identity, having checked it did not write them.
    assert "not_written_by=['Kq9']" in _migration_refused(db.migrate(OWNER))
    assert "not_written_by" in _migration_refused(db.migrate(OWNER, ["Kq9", "someone"]))
    assert db.migrate(OWNER, [OTHER[0]]) == fx.Success(True)
    assert "given to another store" in _migration_refused(db.migrate(OTHER, [OWNER[0]]))
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []
    assert db.report([OWNER[1], OTHER[1]]) == [
        LegacyStore(*OTHER, "taken", (OWNER[0],)),
        LegacyStore(*OWNER, "migrated", (OTHER[0],)),
    ]


def test_without_a_binding_a_store_with_legacy_data_does_not_open_empty(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    pair = ("ab/cd+ef==", "notes")
    with as_065():
        db.write(pair, "data")
    assert not _refusal(db, pair).authenticated
    db.bind(pair[0])
    assert db.read(pair) == ["data"]


# --- a refusal clears, and is seen ---------------------------------------------


def test_a_refused_store_opens_on_the_same_server_once_migrated(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    db.bind(OTHER[0])

    def server():
        storage = yield from Server.Storage()
        refused = yield from storage.latest_sequence(*OWNER).exit()  # pyright: ignore[reportArgumentType]
        assert isinstance(refused, fx.Failure)
        assert db.migrate(OWNER, [OTHER[0]]) == fx.Success(True)
        return (yield from storage.latest_sequence(*OWNER))  # pyright: ignore[reportArgumentType]

    assert db.run(server) == fx.Success(1)


def test_a_refusal_is_logged_once_per_store(db: _Db, as_065: Callable[[], _As065]) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    db.bind(OTHER[0])
    entries: list[logger.Options] = []

    def server():
        storage = yield from Server.Storage()
        for _ in range(3):
            yield from storage.latest_sequence(*OWNER).exit()  # pyright: ignore[reportArgumentType]

    fx.run_blocking(
        fx.scoped(fx.gen(server))
        .pipe(fx.provide(db.storage()))
        .pipe(fx.provide(logger.layer([fx.Logger.make(entries.append)])))
    )
    warnings = [e for e in entries if e.log_level == fx.LogLevel.WARN]
    assert len(warnings) == 1
    assert str(warnings[0].message[0]).startswith(f"Store {OWNER[1]!r} of {OWNER[0]!r}")


# --- a 0.6.5 node writing after the upgrade --------------------------------------


def test_a_store_a_0_6_5_node_split_serves_its_own_tables_and_cannot_be_migrated(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    pair = ("roll/ing==", "s")
    db.bind(pair[0])
    db.write(pair, "new")
    with as_065():
        db.write(pair, "old")
    assert db.read(pair) == ["new"]
    assert "cannot be merged" in _migration_refused(db.migrate(pair))
    assert db.report([pair[1]]) == [LegacyStore(*pair, "split")]


def test_the_report_lists_stores_waiting_for_their_next_request(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    uuid = "0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10"
    with as_065():
        for pair in [OWNER, (uuid, "notes/2024"), (uuid, "notes"), ("pk", "main")]:
            db.bind(pair[0])
            db.write(pair, "x")
    assert db.report(["main", "notes/2024", "notes", "absent"]) == [
        LegacyStore(uuid, "notes/2024", "pending"),
        LegacyStore(*OWNER, "pending"),
    ]
    assert db.migrate(OWNER) == fx.Success(True)
    assert db.report(["main"]) == [LegacyStore(*OWNER, "migrated")]


# --- over the protocol -------------------------------------------------------------


def _entries(tag: str) -> list[Entry]:
    make = new(Entry, disable_checks=True)
    return [
        make(id=J.make_entry_id_unsafe(), event="Noted", primary_key=f"{tag}-{i}", payload=b"x")
        for i in range(2)
    ]


type _Steps = Callable[
    [EventLogRemoteService, Callable[[str], IdentityService]], fx.Effect[Any, Any, Scope]
]


def _over_rpc(db: _Db, steps: _Steps) -> fx.Exit[Any, Any]:
    """``steps(remote, identity)`` against an encrypted server on ``db``;
    ``identity(public_key)`` gives an identity with that key."""

    def body():
        handlers = yield from Server.layer_rpc_handlers.build()
        client: Any = yield from rpc_test.make_client(M.EventLogRemoteRpcs).pipe(
            fx.provide(handlers)
        )
        encryption = yield from EventLogEncryption()
        remote = yield from (
            make_encrypted.pipe(fx.provide_service(EventLogRemoteClient, client))
            .pipe(fx.provide_service(EventLogEncryption, encryption))
            .pipe(fx.provide(L.layer_registry))
        )
        return (yield from steps(remote, lambda key: IdentityService(key, redacted(bytes(32)))))

    return fx.run_blocking(
        fx.scoped(fx.gen(body)).pipe(fx.provide(fx.layer.merge(db.storage(), layer_subtle))).exit()
    )


def _write_over_rpc(db: _Db, pairs: Sequence[tuple[str, str]]) -> None:
    def steps(remote: EventLogRemoteService, identity: Callable[[str], IdentityService]):
        def body():
            for key, store in pairs:
                yield from remote.write(
                    identity=identity(key), store_id=StoreId(store), entries=_entries(key)
                )

        return fx.gen(body)

    assert isinstance(_over_rpc(db, steps), fx.Success)


def _changes_over_rpc(db: _Db, pair: tuple[str, str]) -> fx.Exit[Any, Any]:
    def steps(remote: EventLogRemoteService, identity: Callable[[str], IdentityService]):
        def body():
            changes = yield from remote.changes(
                identity=identity(pair[0]), store_id=StoreId(pair[1]), start_sequence=0
            )
            return (yield from changes.take_n(2).timeout("3 seconds").exit())

        return fx.gen(body)

    ran = _over_rpc(db, steps)
    assert isinstance(ran, fx.Success)
    return ran.value


def test_a_store_written_through_a_0_6_5_server_syncs_after_the_upgrade(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    pairs = [OWNER, ("0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10", "notes/2024")]
    with as_065():
        _write_over_rpc(db, pairs)
    for pair in pairs:
        found = _changes_over_rpc(db, pair)
        assert isinstance(found, fx.Success)
        assert len(found.value) == 2


def test_a_client_is_told_its_store_waits_for_the_operator(
    db: _Db, as_065: Callable[[], _As065]
) -> None:
    with as_065():
        _write_over_rpc(db, [OWNER])
    db.bind(OTHER[0])
    found = _changes_over_rpc(db, OWNER)
    assert isinstance(found, fx.Failure)
    error = found.cause.squash()
    protocol = getattr(error, "cause", None)
    assert isinstance(protocol, M.EventLogProtocolError)
    assert protocol.code == "InternalServerError"
    assert protocol.store_id == OWNER[1]
    assert "operator must migrate" in protocol.message
    assert OTHER[0] not in protocol.message.replace(OWNER[0], "")
