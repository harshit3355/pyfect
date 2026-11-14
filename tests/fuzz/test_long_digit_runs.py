"""Every fuzz target reads digit runs longer than Python's ``int`` reads.

``int(text)`` and ``str(n)`` raise past 4300 digits, where JavaScript's ``BigInt``,
``Number`` and ``String`` read and print any length, so a parser that hands a run of
digits from its input to ``int`` crashes on a long one (a ``BigDecimal`` with 6578
digits parsed, then ``format()`` raised). Each corpus seed is replayed with all its
digit runs, then each of its first runs alone, made 5000 digits long; a crash fails
as in ``test_fuzz.py``. Parsers convert through ``pyfect._digits.to_int`` and print
through ``pyfect._js.int_text``, which read and write any length.
"""

from __future__ import annotations

import re

import pytest

from ._harness import check, corpus
from .targets import TARGETS, Target

_RUN = re.compile(rb"[0-9]+")
_LONG = b"7" * 5000
_EACH = 40
"""Runs of a seed stretched one at a time; the rest are stretched only all together."""


def _stretched(seed: bytes) -> list[bytes]:
    runs = list(_RUN.finditer(seed))
    if not runs:
        return []
    alone = [seed[: run.start()] + _LONG + seed[run.end() :] for run in runs[:_EACH]]
    return [_RUN.sub(_LONG, seed), *alone]


_ALL = sorted(TARGETS.values(), key=lambda found: found.name)


@pytest.mark.parametrize("found", _ALL, ids=lambda found: found.name)
def test_long_digit_runs_do_not_crash(found: Target) -> None:
    for path in corpus(found.name):
        for data in _stretched(path.read_bytes()):
            check(found, data)
