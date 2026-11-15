"""HTTP dates at the edge of what ``datetime`` holds parse to a value or an
``Err``, never an exception: a peer's ``Retry-After`` or ``If-Modified-Since``
must not turn into a defect."""

import itertools

import pytest

from pyfect.http import headers as h
from pyfect.result import Err, Ok

_EDGES = [
    f"{weekday}, {day:02d} {month} {year:04d} {hour:02d}:{minute:02d}:{second:02d} GMT"
    for weekday, (day, month, year), (hour, minute, second) in itertools.product(
        ["Fri", "Mon"],
        [(31, "Dec", 9999), (1, "Jan", 1), (28, "Feb", 9999), (31, "Dec", 1)],
        [(23, 59, 60), (23, 59, 59), (0, 0, 0), (0, 0, 60)],
    )
]


@pytest.mark.parametrize("text", [*_EDGES, "Friday, 31-Dec-99 23:59:60 GMT"])
def test_http_dates_at_the_edges_never_raise(text: str) -> None:
    assert isinstance(h.parse_http_date(text), (Ok, Err))
    assert isinstance(h.parse_retry_after(text), (Ok, Err))


def test_a_leap_second_past_the_last_datetime_is_not_a_date() -> None:
    date = "Fri, 31 Dec 9999 23:59:60 GMT"
    assert isinstance(h.parse_http_date(date), Err)
    assert isinstance(h.parse_retry_after(date), Err)
