"""Storage of an encrypted event log server in a SQL database (Effect's
``eventlog/SqlEventLogServerEncrypted``), on SQLite, PostgreSQL, MySQL or
SQL Server, with remote compaction.

Each identity and store has a table of batches, named by a hash of the
pair under ``entry_table_prefix``, a table of the entry ids it holds with
the sequence each was first stored at, and a table of snapshot batches.
A batch is stored when one of its ids is new; sequences start at 1.
``remote_id_table`` keeps the server's remote id,
``<entry_table_prefix>_session_auth_bindings`` the signing key bound to
each public key, and ``<entry_table_prefix>_compaction_*`` the compaction
state of every store.

Up to 0.6.5 tables were named by ``publicKey/storeId``, which two pairs
share when it holds more than one ``/``. A pair whose key has one ``/``
keeps its tables. Any other pair whose 0.6.5 tables hold batches gets them
on its first request when its public key is the only one sharing that name
that has authenticated (has a session auth binding); otherwise its
operations die with ``LegacyStoreNeedsMigration`` until the operator runs
``migrate_legacy_store``. ``legacy_stores`` lists such stores. See
https://pyfect.dev/docs/eventlog-upgrade-0-6-7.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pyfect._core import Effect
from pyfect._public import publish
from pyfect.crypto.digest import Digest
from pyfect.crypto.digest import layer_web_crypto as digest_layer_web_crypto
from pyfect.eventlog._server_encrypted.models import CompactionOptions
from pyfect.eventlog._server_encrypted.storage import Storage
from pyfect.eventlog._sql_server_encrypted import legacy, legacy_report
from pyfect.eventlog._sql_server_encrypted.legacy import (
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
)
from pyfect.eventlog._sql_server_encrypted.legacy_report import LegacyStore, LegacyStoreState
from pyfect.eventlog._sql_server_encrypted.storage import make_storage
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError

__all__ = [
    "LegacyStore",
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "LegacyStoreState",
    "SqlError",
    "layer_storage",
    "layer_storage_subtle",
    "legacy_stores",
    "make_storage",
    "migrate_legacy_store",
]


def migrate_legacy_store(
    public_key: str,
    store_id: str,
    *,
    not_written_by: Sequence[str] = (),
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
) -> Effect[bool, SqlError | LegacyStoreMigrationError, SqlClient | Digest]:
    """Gives the store of ``public_key`` and ``store_id`` the tables 0.6.5
    named ``publicKey/storeId``. The server does this by itself when
    ``public_key`` is the only key sharing that name that has authenticated;
    this is for a store it refused. ``not_written_by`` must name exactly the
    other authenticated keys sharing the name, once you have confirmed that
    none of them wrote the tables. Succeeds with whether the store has them
    now; fails when ``public_key`` never authenticated, other keys may have
    written them, another pair was given them, or the store already holds
    batches of its own."""
    return legacy.with_db(
        entry_table_prefix,
        remote_id_table,
        lambda db, digest: legacy.migrate_legacy_store(
            db, digest, public_key, store_id, not_written_by
        ),
    )


def legacy_stores(
    store_ids: Iterable[str],
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
) -> Effect[list[LegacyStore], SqlError, SqlClient | Digest]:
    """The stores, among every authenticated public key and the app's
    ``store_ids``, whose 0.6.5 tables hold batches under a name another
    pair shares, with whether each is migrated, waits for its next request,
    needs the operator (``"ambiguous"``) or was split by a 0.6.5 node.
    Store ids are not stored, so the app names them."""
    return legacy.with_db(
        entry_table_prefix,
        remote_id_table,
        lambda db, digest: legacy_report.legacy_stores(db, digest, store_ids),
    )


def layer_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
) -> Layer[Storage, SqlError, SqlClient | Digest]:
    """The ``Storage`` of ``make_storage``."""
    return layer_effect(
        Storage,
        make_storage(
            entry_table_prefix=entry_table_prefix,
            remote_id_table=remote_id_table,
            compaction=compaction,
        ),
    )


def layer_storage_subtle(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
) -> Layer[Storage, SqlError, SqlClient]:
    """``layer_storage`` with the Web Crypto ``Digest``."""
    return layer_storage(
        entry_table_prefix=entry_table_prefix,
        remote_id_table=remote_id_table,
        compaction=compaction,
    ).pipe(layer_provide(digest_layer_web_crypto))


publish(globals())
