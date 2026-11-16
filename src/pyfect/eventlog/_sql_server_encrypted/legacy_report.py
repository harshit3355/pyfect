"""The stores whose tables from 0.6.5 or earlier wait for a migration, for
operators (``sql_event_log_server_encrypted.legacy_stores``).

Store ids are not stored anywhere (tables are named by a hash), so the
caller names the ids its app uses; public keys come from the session auth
bindings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pyfect._core import Effect
from pyfect.crypto.digest import DigestService
from pyfect.effect import gen
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.legacy import (
    has_batches,
    holder,
    legacy_key,
    scope_key,
    scope_of,
    writers_among,
)
from pyfect.persistence._columns import column_text
from pyfect.sql.error import SqlError

type LegacyStoreState = Literal["pending", "ambiguous", "split", "migrated", "taken"]


@dataclass(frozen=True, slots=True)
class LegacyStore:
    """A store whose tables from 0.6.5 or earlier hold batches under a name
    another (public key, store id) pair shares.

    ``state``:

    - ``"pending"``: no other identity splitting the name has authenticated;
      the server gives the store its tables on its next request (or
      ``migrate_legacy_store`` does now).
    - ``"ambiguous"``: ``other_keys`` have authenticated too, and may have
      written the tables; the store does not open until the operator
      decides.
    - ``"split"``: the store holds batches under its new tables too: a 0.6.5
      node wrote to it after it opened on a newer version.
    - ``"migrated"``: the store has its tables.
    - ``"taken"``: another pair sharing the name was given them. If this
      store's identity wrote them, that migration went to the wrong pair.

    ``other_keys`` are the other authenticated keys sharing the name.
    """

    public_key: str
    store_id: str
    state: LegacyStoreState
    other_keys: tuple[str, ...] = ()


def legacy_stores(
    db: Db, digest: DigestService, store_ids: Iterable[str]
) -> Effect[list[LegacyStore], SqlError]:
    sql = db.sql

    def body():
        rows = yield from sql("SELECT public_key FROM {}", db.bindings)
        bound = frozenset(column_text(row["public_key"]) for row in rows)
        opened = {
            column_text(row["scope"]) for row in (yield from sql("SELECT scope FROM {}", db.stores))
        }
        ids = sorted(set(store_ids))
        found: list[LegacyStore] = []
        state: LegacyStoreState
        for public_key in sorted(bound):
            for store_id in ids:
                legacy = legacy_key(public_key, store_id)
                key = scope_key(public_key, store_id)
                if key == legacy:
                    continue
                legacy_scope = yield from scope_of(digest, legacy)
                if legacy_scope not in opened or not (yield from has_batches(db, legacy_scope)):
                    continue
                scope = yield from scope_of(digest, key)
                writers = writers_among(public_key, store_id, bound)
                given = yield from holder(db, legacy_scope)
                if given is not None:
                    state = "migrated" if given == scope else "taken"
                    found.append(LegacyStore(public_key, store_id, state, writers.others))
                    continue
                if writers.others:
                    state = "ambiguous"
                elif (yield from has_batches(db, scope)):
                    state = "split"
                else:
                    state = "pending"
                found.append(LegacyStore(public_key, store_id, state, writers.others))
        return found

    return gen(body)


__all__ = ["LegacyStore", "LegacyStoreState", "legacy_stores"]
