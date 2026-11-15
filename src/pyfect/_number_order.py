"""Effect's ``Order.Number`` for Python: ``NaN`` comes before every number
and equals itself. Python's ``<`` is false both ways with ``NaN``, so
``sorted`` leaves it wherever it happens to fall; port an Effect sort or
bound check that uses ``Order.Number`` with these, not with ``sorted`` or the
bare operators.
"""

from __future__ import annotations

import math
from typing import Any, Final, Literal


class _NaN:
    """Stands in for ``NaN`` in a sort key: below every other key."""

    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        return other is not self

    def __le__(self, other: object) -> bool:
        return True

    def __gt__(self, other: object) -> bool:
        return False

    def __ge__(self, other: object) -> bool:
        return other is self

    def __repr__(self) -> str:
        return "NaN"


_NAN: Final = _NaN()


def key(value: Any) -> Any:
    """``value`` as a sort key ordered as Effect's ``Order.Number`` orders
    numbers: a float ``NaN`` (also inside a tuple) sorts first. Anything
    else is left as it is."""
    if isinstance(value, float):
        return _NAN if math.isnan(value) else value
    if type(value) is tuple:
        return tuple(key(item) for item in value)  # pyright: ignore[reportUnknownVariableType]
    return value


def _is_nan(n: float) -> bool:
    # ``math.isnan`` raises on an int past the largest double.
    return isinstance(n, float) and math.isnan(n)


def compare(a: float, b: float) -> Literal[-1, 0, 1]:
    """Effect's ``Order.Number(a, b)``."""
    a_nan, b_nan = _is_nan(a), _is_nan(b)
    if a_nan or b_nan:
        return 0 if a_nan and b_nan else -1 if a_nan else 1
    return 0 if a == b else -1 if a < b else 1


__all__ = ["compare", "key"]
