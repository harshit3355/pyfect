"""(pyfect) Parsing what a peer sends takes time linear in its length.

Each case is input a client controls (a request path, a header, an MCP resource
URI) given to the parser that reads it, at two sizes eight times apart. A new
parser of peer input belongs in this table."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _complexity import is_linear

from pyfect.http.find_my_way._router import (
    _safe_decode_uri,  # pyright: ignore[reportPrivateUsage]
)

type Case = Callable[[int], Callable[[], object]]


def _percent_25_path(n: int) -> Callable[[], object]:
    path = "/" + "%25" * n
    return lambda: _safe_decode_uri(path)


CASES: dict[str, Case] = {
    "find-my-way path with %25 runs": _percent_25_path,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_peer_input_is_parsed_in_linear_time(name: str) -> None:
    assert is_linear(CASES[name], 20_000)


def test_percent_25_is_kept_encoded_for_parameters() -> None:
    assert _safe_decode_uri("/a%25b%41?q") == ("/a%25bA", "q", True)
    assert _safe_decode_uri("/%25%25") == ("/%25%25", "", True)
