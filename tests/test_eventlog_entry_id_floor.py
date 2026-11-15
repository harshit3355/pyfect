"""Local entry ids follow the journal's latest id, except one a peer could
not have written: malformed, or more than a day ahead of the clock. Such an
id used to make every later local write fail, also after reopening."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect.eventlog import sql_event_journal
from pyfect.eventlog.event_journal import (
    Entry,
    EntryId,
    EntryWithConflicts,
    EventJournal,
    RemoteEntry,
    RemoteId,
    layer_memory,
)
from pyfect.layer import Layer
from pyfect.sql import sqlite

POISON = [EntryId(b"\xff" * 16), EntryId(b"\xff" * 4), EntryId(b"\xff" * 7)]


def _replay(_: Sequence[EntryWithConflicts]) -> fx.Effect[None]:
    return fx.succeed(None)


def _steps(poison: EntryId):
    def body():
        journal = yield from EventJournal()
        before = yield from journal.write(
            event="Note", primary_key="n1", payload=b"{}", effect=lambda e: fx.succeed(e.id)
        )
        poisoned = Entry(id=poison, event="Note", primary_key="x", payload=b"{}")
        yield from journal.write_from_remote(
            remote_id=RemoteId(bytes(16)),
            entries=[RemoteEntry(remote_sequence=1, entry=poisoned)],
            effect=_replay,
        )
        after = yield from journal.write(
            event="Note", primary_key="n2", payload=b"{}", effect=lambda e: fx.succeed(e.id)
        )
        assert after > before
        return after

    return fx.gen(body)


def _again():
    def body():
        journal = yield from EventJournal()
        return (
            yield from journal.write(
                event="Note", primary_key="n3", payload=b"{}", effect=lambda e: fx.succeed(e.id)
            )
        )

    return fx.gen(body)


def _run(program: Any, journal: Layer[Any, Any, Any]) -> object:
    return fx.run_blocking(fx.scoped(program).pipe(fx.provide(journal)).or_die())


def _sql(path: Path) -> Layer[Any, Any, Any]:
    return sql_event_journal.layer().pipe(
        fx.provide(sqlite.layer(sqlite.SqliteClientConfig(filename=str(path))))
    )


@pytest.mark.parametrize("poison", POISON, ids=["ceiling", "4_bytes", "7_bytes"])
def test_memory_journal_writes_after_importing_an_impossible_id(poison: EntryId) -> None:
    _run(_steps(poison), layer_memory)


@pytest.mark.parametrize("poison", POISON, ids=["ceiling", "4_bytes", "7_bytes"])
def test_sql_journal_writes_after_importing_an_impossible_id_also_after_reopening(
    poison: EntryId, tmp_path: Path
) -> None:
    db = tmp_path / "journal.db"
    first = _run(_steps(poison), _sql(db))
    later = _run(_again(), _sql(db))
    assert isinstance(first, bytes)
    assert isinstance(later, bytes)
    assert later > first
