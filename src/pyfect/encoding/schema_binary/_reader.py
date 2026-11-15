"""SchemaBinary's bounds-checked reader over one frame's bytes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never

from pyfect.encoding.schema_binary import _dictionary as D
from pyfect.encoding.schema_binary import _wire as W
from pyfect.schema import ParseOptions
from pyfect.schema.issue import Issue


@dataclass(slots=True, eq=False)
class Reader:
    """``end`` bounds the region being read: ``enter`` narrows it to a child
    value, ``exit`` restores it past the child."""

    buf: bytes
    pos: int
    end: int
    options: ParseOptions
    positional: bool
    dict_: D.DictRead | None = None
    reject_unknown_fields: bool = False
    intern: list[object] | None = None
    """Handed to a row-run field's immediate consumer, then cleared."""
    nesting: int = 0
    path: list[object] = field(default_factory=list[object])
    expansion: int | None = None
    """What back-references may still name, in bytes of the values they
    name (``None``: unbounded). A schema pass walks every name."""
    sizes: dict[int, int] = field(default_factory=dict[int, int])
    """The encoded size of each value a back-reference can name, by id."""

    def keep[V](self, value: V, size: int) -> V:
        """``value``, decoded from ``size`` bytes, joins a back-reference table."""
        if self.expansion is not None:
            self.sizes[id(value)] = max(size, self.sizes.get(id(value), 0))
        return value

    def referenced[V](self, value: V) -> V:
        """``value``, named again by a back-reference."""
        if self.expansion is not None:
            self.expansion -= max(self.sizes.get(id(value), 0), 1)
            if self.expansion < 0:
                raise self.fail("back-references within max_expanded_size")
        return value

    @property
    def remaining(self) -> int:
        return self.end - self.pos

    def error(self, issue: Issue) -> W.IssueError:
        return W.at_path(self.path, issue)

    def fail(self, expected: str, input: object = W.NO_INPUT) -> W.IssueError:
        return self.error(W.invalid_value(expected, input, self.options))

    def _incomplete(self) -> Never:
        raise self.fail("complete value")

    def byte(self) -> int:
        if self.pos >= self.end:
            self._incomplete()
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def take(self, n: int) -> bytes:
        if self.pos + n > self.end:
            self._incomplete()
        out = self.buf[self.pos : self.pos + n]
        self.pos += n
        return out

    def enter(self, length: int) -> int:
        if self.pos + length > self.end:
            self._incomplete()
        saved = self.end
        self.end = self.pos + length
        return saved

    def exit(self, saved: int) -> None:
        self.pos = self.end
        self.end = saved

    def read_utf8(self, n: int) -> str:
        data = self.take(n)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise self.fail("utf-8") from error

    def uvarint(self) -> int:
        value = 0
        for i in range(10):
            b = self.byte()
            chunk = (b & 0x7F) << (7 * i)
            if chunk > W.MAX_SAFE - value:
                raise self.fail("safe integer length")
            value += chunk
            if b < 0x80:
                return value
        raise self.fail("uvarint")

    def field_tag(self) -> int:
        """Field tags are capped at 35 bits."""
        value = 0
        for i in range(5):
            b = self.byte()
            if i == 4 and b >= 0x80:
                raise self.fail("uvarint")
            value |= (b & 0x7F) << (7 * i)
            if b < 0x80:
                break
        return value

    def uvarint_big(self, max_bytes: int | None = None) -> int:
        """Reads the run once, then builds the int by halves: shifting a growing int per
        byte made a run of N bytes cost O(N^2)."""
        start = self.pos
        while self.byte() >= 0x80:
            if max_bytes is not None and self.pos - start >= max_bytes:
                raise self.fail("safe integer length")
        return _from_groups(bytes(self.buf[start : self.pos]))

    def skip_varint(self) -> None:
        """Scans without accumulating an attacker-controlled integer."""
        while self.byte() >= 0x80:
            pass

    def number_varint(self) -> float:
        start = self.pos
        value = 0
        for i in range(W.NUMBER_VARINT_MAX_BYTES):
            b = self.byte()
            value |= (b & 0x7F) << (7 * i)
            if b < 0x80:
                return W.sign_magnitude(value)
        # Wider schema-proven integers: past the safe range they are the
        # float JavaScript reads, which an integer check then rejects.
        self.pos = start
        # A finite double's sign-magnitude code fits in 1025 bits.
        code = self.uvarint_big(_NUMBER_VARINT_FALLBACK_MAX_BYTES)
        magnitude = code >> 1
        if magnitude <= W.MAX_SAFE:
            return W.sign_magnitude(code)
        number = W.as_float(magnitude)
        if number is None:
            raise self.fail("safe integer length")
        return -number if code & 1 else number

    def zigzag(self) -> int:
        u = self.uvarint_big()
        return -((u + 1) >> 1) if u & 1 else u >> 1

    def f64(self) -> float:
        return W.F64.unpack(self.take(8))[0]

    def i64(self) -> int:
        return W.I64.unpack(self.take(8))[0]

    def u64(self) -> int:
        return W.U64.unpack(self.take(8))[0]

    def u32le(self) -> int:
        return W.U32.unpack(self.take(4))[0]

    def i32le(self) -> int:
        return W.I32.unpack(self.take(4))[0]


_NUMBER_VARINT_FALLBACK_MAX_BYTES = 147


def _from_groups(groups: bytes) -> int:
    """The value of little-endian 7-bit ``groups``, in O(n log n)."""
    if len(groups) <= 64:
        value = 0
        for i, b in enumerate(groups):
            value |= (b & 0x7F) << (7 * i)
        return value
    mid = len(groups) // 2
    return _from_groups(groups[:mid]) | (_from_groups(groups[mid:]) << (7 * mid))
