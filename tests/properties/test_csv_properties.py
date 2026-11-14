"""Csv decoding does not depend on how its input is split into chunks.

Effect 4.1.4 (#10456) found records parsed before an error dropped when the error came in the
same chunk, though they were emitted when it came in a later one. This draws CSV text, valid
or not, and checks that every split of it gives the same records, then the same error.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

import pyfect as fx
from pyfect import run, stream
from pyfect.encoding import csv
from pyfect.exit import Failure
from pyfect.result import Ok

_CELL = st.text(alphabet='ab"\n,', max_size=4)
_TEXT = st.lists(st.lists(_CELL, min_size=1, max_size=3), max_size=5).map(
    lambda rows: "\n".join(",".join(row) for row in rows)
)


def _decode(chunks: list[str], headers: bool) -> tuple[list[Any], tuple[str, str] | None]:
    values: list[Any] = []

    def push(value: Any) -> fx.Effect[None]:
        return fx.sync(lambda: values.append(value))

    exit = run.run_sync_exit(
        stream.from_iterable(chunks, chunk_size=1)
        .pipe_through_channel(csv.decode_string(headers=headers))
        .run_for_each(push)
    )
    if not isinstance(exit, Failure):
        return values, None
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    error: csv.CsvError = found.value
    return values, (error.kind, error.message)


@given(
    text=_TEXT,
    cuts=st.lists(st.integers(min_value=0, max_value=40), max_size=4),
    headers=st.booleans(),
)
def test_records_and_errors_do_not_depend_on_chunks(
    text: str, cuts: list[int], headers: bool
) -> None:
    points = sorted({cut % (len(text) + 1) for cut in cuts})
    chunks = [text[a:b] for a, b in zip([0, *points], [*points, len(text)], strict=True)]
    assert _decode(chunks, headers) == _decode([text], headers)
    assert _decode(list(text), headers) == _decode([text], headers)
