"""Which tables hold a store, and the stores 0.6.5 and earlier named ambiguously.

Up to 0.6.5 a (public key, store id) pair named its tables by
``publicKey/storeId`` (as Effect does), which two pairs can share when the
text has more than one ``/``: ``("a/b", "c")`` and ``("a", "b/c")``. Text
with exactly one ``/`` splits back to one pair, so such a pair keeps that
key and its tables. Every other pair has a key that holds no ``/``.

The tables a legacy key named may hold either pair's batches, and the
server cannot tell (it cannot read them). So a store whose legacy tables
hold batches, and which was never opened under its new key, does not open:
it fails with ``LegacyStoreNeedsMigration`` until its owner calls
``migrate_legacy_store``, which gives the pair the legacy tables (one pair
at most) by a row of ``<prefix>_scope_aliases``.
"""

from __future__ import annotations

from typing import Never

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import quote
from pyfect._text_keys import key_bytes
from pyfect.crypto.digest import Digest, DigestService, sha256
from pyfect.effect import fail, gen
from pyfect.eventlog._server_encrypted.models import make_compaction_config
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.tables import create_global_tables
from pyfect.persistence._columns import column_int
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError


class LegacyStoreNeedsMigration(S.TaggedError, tag="LegacyStoreNeedsMigration"):
    """The store's tables from 0.6.5 or earlier hold batches that another
    (public key, store id) pair may have written. Its owner calls
    ``migrate_legacy_store(public_key, store_id)`` once to keep them."""

    public_key: str = S.field(S.String, key="publicKey")
    store_id: str = S.field(S.String, key="storeId")

    @property
    def message(self) -> str:
        return (
            f"Store {self.store_id!r} of {self.public_key!r} has tables from pyfect 0.6.5 or "
            "earlier that another store may share: call "
            "sql_event_log_server_encrypted.migrate_legacy_store to keep them"
        )


class LegacyStoreMigrationError(S.TaggedError, tag="LegacyStoreMigrationError"):
    """``migrate_legacy_store`` refused: the legacy tables went to another
    pair, or the store already holds batches under its new key."""

    message: str = S.field(S.String)


def legacy_key(public_key: str, store_id: str) -> str:
    return f"{public_key}/{store_id}"


def scope_key(public_key: str, store_id: str) -> str:
    """The key naming the pair's tables: the legacy key when it splits back
    to this pair alone (one ``/``), else JSON with no ``/`` in it."""
    legacy = legacy_key(public_key, store_id)
    if legacy.count("/") == 1:
        return legacy
    pair = f"[{quote(public_key)},{quote(store_id)}]"
    return "\0" + pair.replace("/", "\\u002f")


def aliases_table(prefix: str) -> str:
    return f"{prefix}_scope_aliases"


def _scope(digest: DigestService, key: str) -> Effect[str]:
    return digest.digest_hex(sha256, key_bytes(key)).map(lambda hex: hex[:16])


def _has_batches(db: Db, scope: str) -> Effect[bool, SqlError]:
    """Whether the store ``scope`` was opened and has stored a batch (its
    row's next sequence survives pruning). Every version creates the row
    on a store's first open."""

    def body():
        rows = yield from db.sql("SELECT next_sequence FROM {} WHERE scope = {}", db.stores, scope)
        if not rows:
            return False
        if column_int(rows[0]["next_sequence"]) > 1:
            return True
        return (yield from db.max_last_sequence(db.scope_tables(scope).table)) > 0

    return gen(body)


def _alias(db: Db, column: str, value: str) -> Effect[list[tuple[str, str]], SqlError]:
    sql = db.sql
    return sql(
        "SELECT legacy_scope, scope FROM {} WHERE {} = {}",
        sql.identifier(aliases_table(db.prefix)),
        sql.identifier(column),
        value,
    ).map(lambda rows: [(str(row["legacy_scope"]), str(row["scope"])) for row in rows])


def resolve_scope(
    db: Db, digest: DigestService, public_key: str, store_id: str
) -> Effect[str, SqlError | LegacyStoreNeedsMigration]:
    """The scope whose tables hold the pair's store."""

    def body():
        key = scope_key(public_key, store_id)
        scope = yield from _scope(digest, key)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return scope
        adopted = yield from _alias(db, "scope", scope)
        if adopted:
            return adopted[0][0]
        legacy_scope = yield from _scope(digest, legacy)
        if (yield from _alias(db, "legacy_scope", legacy_scope)):
            return scope  # another pair keeps the legacy tables
        if (yield from _has_batches(db, scope)) or not (yield from _has_batches(db, legacy_scope)):
            return scope
        return (
            yield from fail(LegacyStoreNeedsMigration(public_key=public_key, store_id=store_id))
        )

    return gen(body)


def migrate_legacy_store(
    db: Db, digest: DigestService, public_key: str, store_id: str
) -> Effect[bool, SqlError | LegacyStoreMigrationError]:
    """Gives the pair its tables from 0.6.5 or earlier; whether it has them
    now (``False``: it has none, or never needed a new key)."""
    sql = db.sql

    def refuse(message: str) -> Effect[Never, LegacyStoreMigrationError]:
        return fail(LegacyStoreMigrationError(message=message))

    def body():
        key = scope_key(public_key, store_id)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return False
        scope = yield from _scope(digest, key)
        legacy_scope = yield from _scope(digest, legacy)
        claimed = yield from _alias(db, "legacy_scope", legacy_scope)
        if claimed:
            if claimed[0][1] == scope:
                return True
            return (yield from refuse(f"The tables of {legacy!r} were given to another store"))
        if not (yield from _has_batches(db, legacy_scope)):
            return False
        if (yield from _has_batches(db, scope)):
            return (
                yield from refuse(
                    f"Store {store_id!r} of {public_key!r} already holds batches of its own"
                )
            )
        yield from sql(
            "INSERT INTO {} (legacy_scope, scope) VALUES ({}, {})",
            sql.identifier(aliases_table(db.prefix)),
            legacy_scope,
            scope,
        )
        return True

    return sql.with_transaction(gen(body))


def migrate_legacy_store_effect(
    public_key: str,
    store_id: str,
    *,
    entry_table_prefix: str,
    remote_id_table: str,
) -> Effect[bool, SqlError | LegacyStoreMigrationError, SqlClient | Digest]:
    def body():
        digest = yield from Digest()
        sql: SqlClientService = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config()
        yield from create_global_tables(sql, entry_table_prefix, remote_id_table)
        db = Db(sql, entry_table_prefix, config)
        return (yield from migrate_legacy_store(db, digest, public_key, store_id))

    return gen(body)


__all__ = [
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "aliases_table",
    "legacy_key",
    "migrate_legacy_store",
    "migrate_legacy_store_effect",
    "resolve_scope",
    "scope_key",
]
