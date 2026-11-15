"""The httpx client decodes a response's content codings in bounded pieces,
so ``with_body_limit`` sees each piece before more is inflated: httpx's own
decoders inflate a whole network chunk at once, and stacked codings turn a
few hundred bytes into gigabytes in one call."""

from __future__ import annotations

import gzip
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

import pyfect as fx
from pyfect.byte_size import ByteSize
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient
from pyfect.http.response import is_too_large, with_body_limit
from pyfect.result import Err, Ok, Result

_MIB = 1024 * 1024


class _Network(httpx.AsyncByteStream):
    """A body arriving in 16 KiB chunks (httpx reads a whole ``content=`` at once)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for start in range(0, len(self._body), 16 * 1024):
            yield self._body[start : start + 16 * 1024]


def _get(body: bytes, encoding: str, limit: int | None) -> tuple[Result[bytes, Any], int]:
    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {"content-encoding": encoding}
        return httpx.Response(200, stream=_Network(body), headers=headers)

    @fx.fn
    def read():
        http = yield from HttpClient()
        response = yield from http.get("http://upstream/")
        if limit is not None:
            response = with_body_limit(response, ByteSize(limit))
        return (yield from response.bytes_)

    layer = httpx_client.layer_with(transport=httpx.MockTransport(handler))
    tracemalloc.start()
    try:
        outcome = fx.run_blocking(fx.scoped(read()).pipe(fx.provide(layer)).result())
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return outcome, peak


def test_a_stacked_gzip_response_is_refused_before_it_inflates():
    body = gzip.compress(gzip.compress(bytes(64 * _MIB), 9), 9)
    outcome, peak = _get(body, "gzip, gzip", 1024)
    assert isinstance(outcome, Err)
    assert is_too_large(outcome.error)
    assert peak < 8 * _MIB, peak / _MIB


def test_a_single_gzip_response_is_refused_before_it_inflates():
    body = gzip.compress(bytes(32 * _MIB), 9)
    outcome, peak = _get(body, "gzip", 1024)
    assert isinstance(outcome, Err)
    assert peak < 8 * _MIB, peak / _MIB


def _raw_deflate(data: bytes) -> bytes:
    return zlib.compress(data, wbits=-15)


def _gzip_twice(data: bytes) -> bytes:
    return gzip.compress(gzip.compress(data))


def _same(data: bytes) -> bytes:
    return data


@pytest.mark.parametrize(
    ("encoding", "encode"),
    [
        ("gzip", gzip.compress),
        ("deflate", zlib.compress),
        ("deflate", _raw_deflate),  # httpx reads a headerless deflate body as raw deflate
        ("gzip, gzip", _gzip_twice),
        ("identity", _same),
        ("x-unknown", _same),  # httpx passes unknown codings through
    ],
)
def test_codings_decode_as_httpx_decodes_them(encoding: str, encode: Callable[[bytes], bytes]):
    data = b"hello world " * 20_000
    outcome, _peak = _get(encode(data), encoding, None)
    assert outcome == Ok(data)


def test_a_brotli_response_decodes():
    brotli = pytest.importorskip("brotlicffi")
    data = b"hello world " * 20_000
    outcome, _peak = _get(brotli.compress(data), "br", None)
    assert outcome == Ok(data)


def test_a_corrupt_body_fails():
    outcome, _peak = _get(b"not gzip", "gzip", None)
    assert isinstance(outcome, Err)
