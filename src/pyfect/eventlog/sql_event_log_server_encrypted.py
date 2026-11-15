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
keeps its tables; any other pair whose 0.6.5 tables hold batches does not
open (its operations die with ``LegacyStoreNeedsMigration``) until its
owner runs ``migrate_legacy_store`` once.
"""

from __future__ import annotations

from pyfect._core import Effect
from pyfect._public import publish
from pyfect.crypto.digest import Digest
from pyfect.crypto.digest import layer_web_crypto as digest_layer_web_crypto
from pyfect.eventlog._server_encrypted.models import CompactionOptions
from pyfect.eventlog._server_encrypted.storage import Storage
from pyfect.eventlog._sql_server_encrypted.legacy import (
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
    migrate_legacy_store_effect,
)
from pyfect.eventlog._sql_server_encrypted.storage import make_storage
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError

__all__ = [
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "SqlError",
    "layer_storage",
    "layer_storage_subtle",
    "make_storage",
    "migrate_legacy_store",
]


def migrate_legacy_store(
    public_key: str,
    store_id: str,
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
) -> Effect[bool, SqlError | LegacyStoreMigrationError, SqlClient | Digest]:
    """Gives the store of ``public_key`` and ``store_id`` the tables 0.6.5
    named ``publicKey/storeId``, as their owner: run it once for a store
    whose operations die with ``LegacyStoreNeedsMigration``, and only for
    the pair that wrote them (another pair joining to the same text may
    have). Succeeds with whether the store has them now; fails when another
    pair was given them or the store already holds batches of its own."""
    return migrate_legacy_store_effect(
        public_key,
        store_id,
        entry_table_prefix=entry_table_prefix,
        remote_id_table=remote_id_table,
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
