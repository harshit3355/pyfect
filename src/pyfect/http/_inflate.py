"""A response's content codings decoded lazily, in pieces of at most 64 KiB.

httpx's decoders inflate a whole network chunk in one call, so a body limit
applied to their output sees a bomb only after it is in memory. Here each
piece is produced when the reader asks for it, so a limit stops the decoding
after about the limit. Codings are read as httpx reads them: ``gzip``,
``deflate`` (zlib, or raw deflate), ``br`` with the ``brotli`` extra (``Unsupported`` without it);
``identity`` and unknown codings pass the bytes through.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterator, Sequence
from importlib.util import find_spec
from typing import Any, Protocol

PIECE = 64 * 1024


class _Stage(Protocol):
    def pieces(self, data: bytes) -> Iterator[bytes]: ...
    def finish(self) -> Iterator[bytes]: ...


class DecodingError(Exception):
    """The body does not decode by its codings."""


class _Zlib:
    def __init__(self, wbits: int, *, raw_fallback: bool) -> None:
        self._wbits = wbits
        self._decoder = zlib.decompressobj(wbits)
        self._first = raw_fallback

    def pieces(self, data: bytes) -> Iterator[bytes]:
        full = False  # a full piece may leave output inside the decoder
        while (data or full) and not self._decoder.eof:
            try:
                piece = self._decoder.decompress(data, PIECE)
            except zlib.error as error:
                if not self._first:
                    raise DecodingError(str(error)) from error
                # httpx reads a ``deflate`` body without a zlib header as raw deflate.
                self._first = False
                self._decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                continue
            self._first = False
            # Input past the end is dropped, as httpx's decoders ignore it.
            data = self._decoder.unconsumed_tail
            full = len(piece) == PIECE
            if piece:
                yield piece

    def finish(self) -> Iterator[bytes]:
        try:
            rest = self._decoder.flush()
        except zlib.error as error:  # pragma: no cover - flush raises only on corrupt input
            raise DecodingError(str(error)) from error
        if rest:
            yield rest


class _Brotli:
    def __init__(self) -> None:
        from pyfect.http._brotli import decompressor  # the brotli extra

        self._decoder: Any = decompressor()

    def pieces(self, data: bytes) -> Iterator[bytes]:
        decoder = self._decoder
        try:
            yield decoder.process(data, output_buffer_limit=PIECE)
            while not decoder.can_accept_more_data():
                yield decoder.process(b"", output_buffer_limit=PIECE)
        except Exception as error:
            raise DecodingError(str(error)) from error

    def finish(self) -> Iterator[bytes]:
        return iter(())


class Unsupported(Exception):
    """A coding httpx decodes that pyfect cannot decode in bounded pieces here."""


def _stage(coding: str) -> _Stage | None:
    if coding == "gzip":
        return _Zlib(zlib.MAX_WBITS | 16, raw_fallback=False)
    if coding == "deflate":
        return _Zlib(zlib.MAX_WBITS, raw_fallback=True)
    if coding == "br":
        # The brotli extra; without it httpx may still decode ``br`` (``brotli``).
        if find_spec("brotlicffi") is None:
            raise Unsupported(coding)
        return _Brotli()
    return None


class Inflater:
    """The codings of a ``content-encoding`` header, in the order applied."""

    def __init__(self, codings: Sequence[str]) -> None:
        stages = [_stage(coding.strip().lower()) for coding in codings]
        # The coding applied last is decoded first.
        self._stages = [stage for stage in reversed(stages) if stage is not None]

    @property
    def is_identity(self) -> bool:
        return not self._stages

    def feed(self, data: bytes) -> Iterator[bytes]:
        """The decoded pieces of ``data``, produced as they are taken."""
        return self._through(1, self._stages[0].pieces(data)) if self._stages else iter((data,))

    def finish(self) -> Iterator[bytes]:
        """The rest, once the body has ended."""
        for level in range(len(self._stages)):
            yield from self._through(level + 1, self._stages[level].finish())

    def _through(self, level: int, pieces: Iterator[bytes]) -> Iterator[bytes]:
        if level == len(self._stages):
            yield from pieces
            return
        stage = self._stages[level]
        for piece in pieces:
            yield from stage.pieces(piece)
