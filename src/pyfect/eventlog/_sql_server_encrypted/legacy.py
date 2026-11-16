"""Which tables hold a store, and the stores 0.6.5 and earlier named ambiguously.

Up to 0.6.5 a (public key, store id) pair named its tables by
``publicKey/storeId`` (as Effect does), which two pairs can share when the
text has more than one ``/``: ``("a/b", "c")`` and ``("a", "b/c")``. Text
with exactly one ``/`` splits back to one pair, so such a pair keeps that
key and its tables. Every other pair has a key that holds no ``/``.

The tables a legacy key named may hold either pair's batches, and the
server cannot read them. What shows who wrote them is
``<prefix>_session_auth_bindings``: a key that wrote through a server has
authenticated, so it has a binding. A store whose legacy tables hold
batches, and which holds none under its new key, gets them (by a row of
``<prefix>_scope_aliases``, one pair at most) when its key is the only key
splitting the legacy text that has a binding. Otherwise it does not open
(``LegacyStoreNeedsMigration``) until the operator decides, with
``migrate_legacy_store``, naming the other identities that did not write
them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Never

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._json_text import quote
from pyfect.crypto.digest import Digest, DigestService, sha256
from pyfect.effect import fail, gen
from pyfect.eventlog._server_encrypted.models import make_compaction_config
from pyfect.eventlog._sql_server_encrypted.db import CHUNK, Db
from pyfect.eventlog._sql_server_encrypted.tables import create_global_tables
from pyfect.eventlog._store_unavailable import StoreUnavailable
from pyfect.persistence._columns import column_int, column_text
from pyfect.persistence._sql_keys import key_equals
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError

UPGRADE_NOTES = "https://pyfect.dev/docs/eventlog-upgrade-0-6-7"


class LegacyStoreNeedsMigration(S.TaggedError, StoreUnavailable, tag="LegacyStoreNeedsMigration"):
    """The store's tables from 0.6.5 or earlier hold batches, and the
    session auth bindings do not show that this store alone wrote them:
    its key never authenticated, or ``other_keys``, which split the same
    legacy name, did too."""

    public_key: str = S.field(S.String, key="publicKey")
    store_id: str = S.field(S.String, key="storeId")
    authenticated: bool = S.field(S.Boolean, default=False)
    other_keys: tuple[str, ...] = S.field(S.Array(S.String), default=(), key="otherKeys")

    @property
    def message(self) -> str:
        legacy = legacy_key(self.public_key, self.store_id)
        others = ", ".join(repr(key) for key in self.other_keys)
        if self.authenticated:
            why = (
                f"that this store or the store of {others} may have written: each key has "
                "authenticated. Find out which wrote them before migrating them"
            )
        elif others:
            why = (
                f"that the store of {others} may have written, and this store's key has never "
                "authenticated. Do not migrate them to it unless you know it wrote them"
            )
        else:
            why = (
                "and this store's key has never authenticated, so nothing shows it wrote them. "
                "Do not migrate them to it unless you know it did"
            )
        return (
            f"Store {self.store_id!r} of {self.public_key!r} does not open: the tables pyfect "
            f"0.6.5 named {legacy!r} hold batches {why} (see {UPGRADE_NOTES})"
        )

    @property
    def client_message(self) -> str:
        return (
            "This store holds data from before the server's upgrade from pyfect 0.6.5, "
            "which the server's operator must migrate"
        )


class LegacyStoreMigrationError(S.TaggedError, tag="LegacyStoreMigrationError"):
    """``migrate_legacy_store`` refused: nothing shows the pair wrote the
    legacy tables, other identities may have, the tables went to another
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
    return digest.digest_hex(sha256, text_encode(key)).map(lambda hex: hex[:16])


def scope_of(digest: DigestService, key: str) -> Effect[str]:
    """The scope (table name hash) of a scope key or legacy key."""
    return _scope(digest, key)


def has_batches(db: Db, scope: str) -> Effect[bool, SqlError]:
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


def holder(db: Db, legacy_scope: str) -> Effect[str | None, SqlError]:
    """The scope of the pair given the legacy tables, if one was."""
    return db.sql("SELECT scope FROM {} WHERE legacy_scope = {}", db.aliases, legacy_scope).map(
        lambda rows: column_text(rows[0]["scope"]) if rows else None
    )


def split_keys(legacy: str) -> list[str]:
    """The public key of every pair whose legacy key is ``legacy``."""
    return [legacy[:i] for i, c in enumerate(legacy) if c == "/"]


@dataclass(frozen=True, slots=True)
class Writers:
    """Who may have written a pair's legacy tables: whether the pair's key
    has a session auth binding, and the other keys splitting the same
    legacy key that have one."""

    authenticated: bool
    others: tuple[str, ...]

    @property
    def proven(self) -> bool:
        """Only this pair's key can have written them."""
        return self.authenticated and not self.others


def writers_among(public_key: str, store_id: str, bound: Iterable[str]) -> Writers:
    bound = frozenset(bound)
    keys = split_keys(legacy_key(public_key, store_id))
    return Writers(
        public_key in bound, tuple(sorted(k for k in keys if k != public_key and k in bound))
    )


def _writers(db: Db, public_key: str, store_id: str) -> Effect[Writers, SqlError]:
    sql = db.sql

    def body():
        keys = split_keys(legacy_key(public_key, store_id))
        bound: set[str] = set()
        for start in range(0, len(keys), CHUNK):
            chunk = keys[start : start + CHUNK]
            rows = yield from sql(
                "SELECT public_key FROM {} WHERE {}",
                db.bindings,
                sql.join(" OR ", False)([key_equals(sql, "public_key", k) for k in chunk]),
            )
            bound.update(column_text(row["public_key"]) for row in rows)
        # Keep exact matches only, whatever the column's collation.
        return writers_among(public_key, store_id, bound.intersection(keys))

    return gen(body)


def _give(db: Db, legacy_scope: str, scope: str) -> Effect[bool, SqlError]:
    """Gives ``scope`` the legacy tables unless another pair has them;
    whether ``scope`` has them now."""

    def body():
        yield from db.insert_new(
            db.aliases, [{"legacy_scope": legacy_scope, "scope": scope}], ["legacy_scope"]
        )
        return (yield from holder(db, legacy_scope)) == scope

    return gen(body)


@dataclass(frozen=True, slots=True)
class Resolved:
    """The scope holding a pair's store. ``migrated``: it was just given its
    legacy tables. ``split``: its legacy tables hold batches too, which a
    0.6.5 node wrote after the store opened under its new key."""

    scope: str
    event: Literal["migrated", "split"] | None = None


def _unclaimed(
    db: Db, public_key: str, store_id: str, scope: str, legacy_scope: str
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope of a pair whose legacy tables hold batches no pair has."""

    def body():
        writers = yield from _writers(db, public_key, store_id)
        if (yield from has_batches(db, scope)):
            return Resolved(scope, "split" if writers.proven else None)
        if not writers.proven:
            return (
                yield from fail(
                    LegacyStoreNeedsMigration(
                        public_key=public_key,
                        store_id=store_id,
                        authenticated=writers.authenticated,
                        other_keys=writers.others,
                    )
                )
            )
        given = yield from _give(db, legacy_scope, scope)
        return Resolved(legacy_scope, "migrated") if given else Resolved(scope)

    return gen(body)


def resolve_scope(
    db: Db, digest: DigestService, public_key: str, store_id: str
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope whose tables hold the pair's store, giving it its legacy
    tables when the bindings show it alone wrote them."""

    def body():
        key = scope_key(public_key, store_id)
        scope = yield from _scope(digest, key)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return Resolved(scope)
        legacy_scope = yield from _scope(digest, legacy)
        given = yield from holder(db, legacy_scope)
        if given is not None:
            return Resolved(legacy_scope if given == scope else scope)
        if not (yield from has_batches(db, legacy_scope)):
            return Resolved(scope)
        return (yield from _unclaimed(db, public_key, store_id, scope, legacy_scope))

    return gen(body)


def _migration_refusal(
    db: Db, public_key: str, store_id: str, scope: str, not_written_by: Sequence[str]
) -> Effect[str | None, SqlError]:
    """Why the pair may not have its legacy tables, which hold batches."""
    legacy = legacy_key(public_key, store_id)

    def body():
        writers = yield from _writers(db, public_key, store_id)
        others = list(writers.others)
        if not writers.authenticated:
            return (
                f"{public_key!r} has never authenticated (it has no session auth binding), "
                f"so nothing shows that its store {store_id!r} wrote the tables named {legacy!r}"
            )
        if sorted(set(not_written_by)) != others:
            if not others:
                return (
                    f"No other identity that has authenticated shares the name {legacy!r}: "
                    "call it without not_written_by"
                )
            return (
                f"Other identities that have authenticated share the name {legacy!r} and may "
                f"have written its tables: {others!r}. If you have confirmed that none of them "
                f"did, pass not_written_by={others!r}"
            )
        if (yield from has_batches(db, scope)):
            return (
                f"Store {store_id!r} of {public_key!r} already holds batches of its own, so a "
                f"pyfect 0.6.5 node wrote the tables named {legacy!r} after the store opened on "
                "a newer version; the two cannot be merged"
            )
        return None

    return gen(body)


def migrate_legacy_store(
    db: Db,
    digest: DigestService,
    public_key: str,
    store_id: str,
    not_written_by: Sequence[str] = (),
) -> Effect[bool, SqlError | LegacyStoreMigrationError]:
    """Gives the pair its tables from 0.6.5 or earlier; whether it has them
    now (``False``: it has none, or never needed a new key)."""
    sql = db.sql

    def refuse(message: str) -> Effect[Never, LegacyStoreMigrationError]:
        return fail(LegacyStoreMigrationError(message=f"{message} (see {UPGRADE_NOTES})"))

    def body():
        key = scope_key(public_key, store_id)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return False
        scope = yield from _scope(digest, key)
        legacy_scope = yield from _scope(digest, legacy)
        given = yield from holder(db, legacy_scope)
        if given is not None and given != scope:
            return (yield from refuse(f"The tables of {legacy!r} were given to another store"))
        if given is not None or not (yield from has_batches(db, legacy_scope)):
            return given is not None
        refusal = yield from _migration_refusal(db, public_key, store_id, scope, not_written_by)
        if refusal is not None:
            return (yield from refuse(refusal))
        yield from sql(
            "INSERT INTO {} (legacy_scope, scope) VALUES ({}, {})",
            db.aliases,
            legacy_scope,
            scope,
        )
        return True

    return sql.with_transaction(gen(body))


def with_db[A, E](
    entry_table_prefix: str, remote_id_table: str, f: Callable[[Db, DigestService], Effect[A, E]]
) -> Effect[A, E | SqlError, SqlClient | Digest]:
    """Runs ``f`` on the storage's tables, outside a server."""

    def body():
        digest = yield from Digest()
        sql: SqlClientService = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config()
        yield from create_global_tables(sql, entry_table_prefix, remote_id_table)
        return (yield from f(Db(sql, entry_table_prefix, config), digest))

    return gen(body)


__all__ = [
    "UPGRADE_NOTES",
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "Resolved",
    "Writers",
    "aliases_table",
    "has_batches",
    "holder",
    "legacy_key",
    "migrate_legacy_store",
    "resolve_scope",
    "scope_key",
    "scope_of",
    "split_keys",
    "with_db",
    "writers_among",
]
