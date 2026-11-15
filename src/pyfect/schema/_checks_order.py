"""Bound checks for any ordered type (Effect's ``makeIsGreaterThan``,
``makeIsBetween``, ``makeIsMultipleOf``, ...), compared with ``order``
(Effect's ``order``: negative, zero or positive), else Python's operators.
``formatter`` writes a bound in the ``expected`` text
(``format_unknown`` by default); ``annotate`` adds annotations per bound."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from pyfect.logger._text import format_unknown
from pyfect.schema.ast import Filter, filter_of


class SupportsOrder(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...
    def __le__(self, other: Any, /) -> bool: ...
    def __gt__(self, other: Any, /) -> bool: ...
    def __ge__(self, other: Any, /) -> bool: ...


class Bound[T](Protocol):
    """A check maker taking one bound: ``is_greater_than(1)``."""

    def __call__(self, bound: T, /, **annotations: object) -> Filter[T]: ...


class Between[T](Protocol):
    """A check maker taking a range: ``is_between(minimum=1, maximum=3)``."""

    def __call__(
        self,
        *,
        minimum: T,
        maximum: T,
        exclusive_minimum: bool = False,
        exclusive_maximum: bool = False,
        **annotations: object,
    ) -> Filter[T]: ...


type Annotate[T] = Callable[[T], Mapping[str, object]]

type Order[T] = Callable[[T, T], int]
"""Effect's ``Order``: negative, zero or positive as the first value is
below, equal to or above the second."""


class _Compare[T](Protocol):
    def __call__(self, a: T, b: T, /) -> bool: ...


def _relation[T: SupportsOrder](
    order: Order[T] | None, python: _Compare[T], holds: Callable[[int], bool]
) -> _Compare[T]:
    if order is None:
        return python
    return lambda a, b: holds(order(a, b))


def _gt[T: SupportsOrder](order: Order[T] | None) -> _Compare[T]:
    return _relation(order, lambda a, b: a > b, lambda c: c > 0)


def _ge[T: SupportsOrder](order: Order[T] | None) -> _Compare[T]:
    return _relation(order, lambda a, b: a >= b, lambda c: c >= 0)


def _lt[T: SupportsOrder](order: Order[T] | None) -> _Compare[T]:
    return _relation(order, lambda a, b: a < b, lambda c: c < 0)


def _le[T: SupportsOrder](order: Order[T] | None) -> _Compare[T]:
    return _relation(order, lambda a, b: a <= b, lambda c: c <= 0)


def _bound[T: SupportsOrder](
    accepts: Callable[[T, T], bool],
    text: str,
    formatter: Callable[[T], str],
    annotate: Annotate[T] | None,
) -> Bound[T]:
    def make(bound: T, /, **annotations: object) -> Filter[T]:
        extra: Mapping[str, object] = annotate(bound) if annotate is not None else {}
        return filter_of(
            lambda input: accepts(input, bound),
            {"expected": f"a value {text} {formatter(bound)}", **extra, **annotations},
        )

    return make


def make_is_greater_than[T: SupportsOrder](
    *,
    formatter: Callable[[T], str] = format_unknown,
    annotate: Annotate[T] | None = None,
    order: Order[T] | None = None,
) -> Bound[T]:
    return _bound(_gt(order), "greater than", formatter, annotate)


def make_is_greater_than_or_equal_to[T: SupportsOrder](
    *,
    formatter: Callable[[T], str] = format_unknown,
    annotate: Annotate[T] | None = None,
    order: Order[T] | None = None,
) -> Bound[T]:
    return _bound(_ge(order), "greater than or equal to", formatter, annotate)


def make_is_less_than[T: SupportsOrder](
    *,
    formatter: Callable[[T], str] = format_unknown,
    annotate: Annotate[T] | None = None,
    order: Order[T] | None = None,
) -> Bound[T]:
    return _bound(_lt(order), "less than", formatter, annotate)


def make_is_less_than_or_equal_to[T: SupportsOrder](
    *,
    formatter: Callable[[T], str] = format_unknown,
    annotate: Annotate[T] | None = None,
    order: Order[T] | None = None,
) -> Bound[T]:
    return _bound(_le(order), "less than or equal to", formatter, annotate)


type AnnotateBetween[T] = Callable[[T, T, bool, bool], Mapping[str, object]]


def make_is_between[T: SupportsOrder](
    *,
    formatter: Callable[[T], str] = format_unknown,
    annotate: AnnotateBetween[T] | None = None,
    order: Order[T] | None = None,
) -> Between[T]:
    """``annotate(minimum, maximum, exclusive_minimum, exclusive_maximum)``."""
    gt, ge, lt, le = _gt(order), _ge(order), _lt(order), _le(order)

    def make(
        *,
        minimum: T,
        maximum: T,
        exclusive_minimum: bool = False,
        exclusive_maximum: bool = False,
        **annotations: object,
    ) -> Filter[T]:
        def accepts(input: T) -> bool:
            above = gt(input, minimum) if exclusive_minimum else ge(input, minimum)
            below = lt(input, maximum) if exclusive_maximum else le(input, maximum)
            return above and below

        low = formatter(minimum) + (" (excluded)" if exclusive_minimum else "")
        high = formatter(maximum) + (" (excluded)" if exclusive_maximum else "")
        extra: Mapping[str, object] = (
            annotate(minimum, maximum, exclusive_minimum, exclusive_maximum)
            if annotate is not None
            else {}
        )
        return filter_of(
            accepts, {"expected": f"a value between {low} and {high}", **extra, **annotations}
        )

    return make


def make_is_multiple_of[T](
    *,
    is_multiple: Callable[[T, T], bool],
    formatter: Callable[[T], str] = format_unknown,
    annotate: Annotate[T] | None = None,
) -> Bound[T]:
    """``is_multiple(input, divisor)`` decides (Effect takes a remainder
    function and its zero)."""

    def make(divisor: T, /, **annotations: object) -> Filter[T]:
        extra: Mapping[str, object] = annotate(divisor) if annotate is not None else {}
        return filter_of(
            lambda input: is_multiple(input, divisor),
            {
                "expected": f"a value that is a multiple of {formatter(divisor)}",
                **extra,
                **annotations,
            },
        )

    return make
