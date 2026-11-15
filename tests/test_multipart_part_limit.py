"""A multipart body has at most ``MaxParts`` parts, 1000 by default: a
buffered form writes a temporary file for each file part before its schema
runs, so the count must be bounded before the parts are persisted."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import effect, stream
from pyfect.exit import Failure, Success
from pyfect.http import multipart as m

BOUNDARY = "b"
HEADERS = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}


def _body(parts: int) -> bytes:
    part = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="f"; filename="f"\r\n\r\n\r\n'
    return (part * parts + f"--{BOUNDARY}--\r\n").encode()


def _count(parts: int, **provide: Any) -> fx.Exit[int, Any]:
    collected = (
        stream.make(_body(parts))
        .pipe_through_channel(m.make_channel(HEADERS))
        .map_effect(
            lambda part: part.content.run_drain() if isinstance(part, m.File) else effect.void
        )
        .run_count()
    )
    if "max_parts" in provide:
        collected = collected.pipe(effect.provide_service(m.MaxParts, provide["max_parts"]))
    return fx.run_blocking_exit(collected)


def test_parts_are_bounded_by_default():
    assert m.MaxParts.default() == 1000
    assert isinstance(_count(1000), Success)
    exit = _count(1001)
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, m.MultipartError)
    assert error.reason.tag == "TooManyParts"


def test_the_part_limit_is_configurable():
    assert isinstance(_count(3000, max_parts=None), Success)
    assert isinstance(_count(3, max_parts=2), Failure)
