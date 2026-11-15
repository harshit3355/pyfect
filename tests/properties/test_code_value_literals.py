"""An annotation value generated code prints reads back as the same value, or isn't printed.

Effect 4.1.4 (#10532) omits annotations holding objects that aren't plain. Python's analogue is
a subclass of a printable type: an ``IntEnum`` printed as ``<C.A: 1>``, a ``namedtuple`` as a
list. This draws values mixing plain and subclassed ones and checks that whatever
``value_literal`` prints evaluates back to the value (a tuple is printed as a list).
"""

from __future__ import annotations

import collections
import enum
import math
from collections.abc import Sequence
from typing import Any, NamedTuple, cast

from hypothesis import given
from hypothesis import strategies as st

from pyfect.schema.representation._code_builtins import value_literal


class _Level(enum.IntEnum):
    A = 1


class _Name(enum.StrEnum):
    A = "a"


class _Pair(NamedTuple):
    x: int
    y: int


class _Text(str):
    __slots__ = ()


_LEAVES = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text()
    | st.just(_Level.A)
    | st.just(_Name.A)
    | st.just(_Pair(1, 2))
    | st.builds(_Text, st.text())
)


def _containers(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return (
        st.lists(children, max_size=3)
        | st.lists(children, max_size=3).map(tuple)
        | st.dictionaries(st.text(max_size=3), children, max_size=3)
        | st.dictionaries(st.text(max_size=3), children, max_size=3).map(collections.OrderedDict)
    )


def _plain(value: object) -> object:
    """``value`` as printed code reads back: tuples become lists."""
    if type(value) in (list, tuple):
        return [_plain(item) for item in cast("Sequence[object]", value)]
    if type(value) is dict:
        return {key: _plain(item) for key, item in cast("dict[str, object]", value).items()}
    return value


def _same(a: object, b: object) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        b = cast("float", b)
        return (math.isnan(a) and math.isnan(b)) or a == b
    if isinstance(a, list):
        x, y = cast("list[object]", a), cast("list[object]", b)
        return len(x) == len(y) and all(map(_same, x, y))
    if isinstance(a, dict):
        x, y = cast("dict[str, object]", a), cast("dict[str, object]", b)
        return x.keys() == y.keys() and all(_same(x[k], y[k]) for k in x)
    return a == b


@given(value=st.recursive(_LEAVES, _containers, max_leaves=8))
def test_a_printed_value_reads_back_as_itself(value: object) -> None:
    printed = value_literal(value)
    if printed is not None:
        assert _same(eval(printed), _plain(value)), printed
