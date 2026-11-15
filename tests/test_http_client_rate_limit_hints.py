"""What a response teaches ``with_rate_limiter`` holds a key for at most an
hour per request, as its time hints are: a tiny ``ratelimit-limit`` used to
park a key for thousands of years (``window / limit`` per request)."""

import pytest

from pyfect.duration import Duration, seconds
from pyfect.http.client._rate_limit import (
    _header_names,  # pyright: ignore[reportPrivateUsage]
    _Inspector,  # pyright: ignore[reportPrivateUsage]
    _Limits,  # pyright: ignore[reportPrivateUsage]
)
from pyfect.http.headers import Headers

_HOUR_MILLIS = 3_600_000


@pytest.mark.parametrize("limit", ["0.000000001", "1e-300", "0.5", "0.99", "5e-324"])
@pytest.mark.parametrize("reset", [None, "3600", "999999999"])
def test_a_learned_limit_holds_a_request_for_at_most_an_hour(limit: str, reset: str | None) -> None:
    inspector = _Inspector(_header_names({}))
    current = _Limits(1000, seconds(60), initial=True)
    raw = {"ratelimit-limit": limit}
    if reset is not None:
        raw["ratelimit-reset"] = reset
    learned = inspector.limits(current, 0, Headers(raw), 1)
    window: Duration = learned.window
    assert window.to_millis() / learned.limit <= _HOUR_MILLIS


def test_a_sensible_limit_is_still_learned() -> None:
    inspector = _Inspector(_header_names({}))
    current = _Limits(1000, seconds(60), initial=True)
    learned = inspector.limits(current, 0, Headers({"ratelimit-limit": "10"}), 1)
    assert learned.limit == 10
