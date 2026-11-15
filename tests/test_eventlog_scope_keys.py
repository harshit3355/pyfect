"""The SQL encrypted event log server keeps every (public key, store id)
pair in its own scope, and existing stores keep their tables."""

import hashlib
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer
from pyfect.eventlog import event_log_server_encrypted, sql_event_log_server_encrypted
from pyfect.eventlog._sql_server_encrypted.storage import (
    _scope_key,  # pyright: ignore[reportPrivateUsage]
)
from pyfect.eventlog.event_journal import StoreId, make_entry_id_unsafe
from pyfect.eventlog.event_log_encryption import EncryptedBatch
from pyfect.eventlog.event_log_server_encrypted import Storage
from pyfect.layer import Layer
from pyfect.sql import sqlite

PAIRS = [
    ("victim", "notes/2024"),
    ("victim/notes", "2024"),
    ("a/b", "c"),
    ("a", "b/c"),
    ("a/b/c", ""),
    ("", "a/b/c"),
]


def test_scope_keys_are_injective() -> None:
    keys = [_scope_key(public_key, store_id) for public_key, store_id in PAIRS]
    assert len(set(keys)) == len(keys)


def test_a_public_key_without_a_slash_keeps_its_scope_key() -> None:
    # Tables are named from this key: existing stores must keep it.
    assert _scope_key("0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10", "notes/2024") == (
        "0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10/notes/2024"
    )
    table = hashlib.sha256(b"pk/store").hexdigest()[:16]
    assert hashlib.sha256(_scope_key("pk", "store").encode()).hexdigest()[:16] == table


@fx.fn
def _program():
    storage = yield from Storage()
    batch = EncryptedBatch(
        entry_ids=(make_entry_id_unsafe(),), iv=bytes(12), encrypted_batch=b"x" * 32
    )
    yield from storage.write("victim", StoreId("notes/2024"), [batch])
    victim = yield from storage.latest_sequence("victim", StoreId("notes/2024"))
    other = yield from storage.latest_sequence("victim/notes", StoreId("2024"))
    seen = yield from storage.entry_sequences("victim/notes", StoreId("2024"), batch.entry_ids)
    return victim, other, len(seen)


@pytest.mark.parametrize("storage", ["sql", "memory"])
def test_pairs_joining_to_one_string_stay_apart(storage: str) -> None:
    provided: Layer[Any, Any, Any] = (
        sql_event_log_server_encrypted.layer_storage_subtle().pipe(
            layer.provide(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        )
        if storage == "sql"
        else event_log_server_encrypted.layer_storage_memory
    )
    program = fx.scoped(_program()).pipe(fx.provide(provided)).or_die()
    result: tuple[int | None, int | None, int] = fx.run_blocking(program)
    victim, other, seen = result
    assert victim is not None
    assert other is None
    assert seen == 0
