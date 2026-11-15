"""Dict and set keys a peer chooses.

CPython seeds the hash of ``str`` and ``bytes`` per process, but not of
``int``: ``n`` hashes to ``n mod (2**61 - 1)``, so a peer can send any
number of distinct ints with one hash (``k * (2**61 - 1)``), and every
insert into a dict or set of them compares against all the earlier ones.
Tuples and floats combine hashes the peer chooses the same way.

``PeerKeyDict`` and ``PeerKeySet`` key big ints by their seeded byte form,
for maps of scalar ids (request ids). ``check_spread`` refuses keys of any
kind where too many distinct ones share one hash, before a real ``set`` or
``dict`` of them is built (decoded sets and maps).
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator, MutableMapping, MutableSet

_SMALL = 1 << 60
"""Ints below this in size hash to themselves: no two share a hash."""

MAX_SHARED_HASH = 64
"""How many distinct keys may share one hash in ``check_spread``. Floats that
are not crafted reach about 35 (``2.0 ** (61 * k)`` all hash to 1)."""


class HashFlood(ValueError):
    """More than ``MAX_SHARED_HASH`` distinct keys share one hash."""


class _Big:
    """The tag of a big int's key, apart from any value a peer sends."""

    __slots__ = ()


_BIG = _Big()


def peer_key(value: Hashable) -> Hashable:
    """A key for ``value`` that is equal for equal values, whose hash a
    peer cannot choose for a big ``int``. Other values key as themselves."""
    if type(value) is int and not -_SMALL < value < _SMALL:
        return (_BIG, value.to_bytes((value.bit_length() + 8) // 8, "little", signed=True))
    return value


class PeerKeyDict[K: Hashable, V](MutableMapping[K, V]):
    """A ``dict`` whose keys a peer chooses (``peer_key``)."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[Hashable, tuple[K, V]] = {}

    def __getitem__(self, key: K) -> V:
        return self._entries[peer_key(key)][1]

    def __setitem__(self, key: K, value: V) -> None:
        self._entries[peer_key(key)] = (key, value)

    def __delitem__(self, key: K) -> None:
        del self._entries[peer_key(key)]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, Hashable) and peer_key(key) in self._entries

    def __iter__(self) -> Iterator[K]:
        return (key for key, _ in list(self._entries.values()))

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"PeerKeyDict({dict(self._entries.values())!r})"


class PeerKeySet[K: Hashable](MutableSet[K]):
    """A ``set`` whose members a peer chooses (``peer_key``)."""

    __slots__ = ("_members",)

    def __init__(self) -> None:
        self._members: dict[Hashable, K] = {}

    def __contains__(self, value: object) -> bool:
        return isinstance(value, Hashable) and peer_key(value) in self._members

    def __iter__(self) -> Iterator[K]:
        return iter(list(self._members.values()))

    def __len__(self) -> int:
        return len(self._members)

    def add(self, value: K) -> None:
        self._members.setdefault(peer_key(value), value)

    def discard(self, value: K) -> None:
        self._members.pop(peer_key(value), None)

    def __repr__(self) -> str:
        return f"PeerKeySet({list(self._members.values())!r})"


class SpreadGuard:
    """Counts the distinct keys of each hash as keys are added: ``add``
    raises ``HashFlood`` past ``limit`` of one hash, at a cost of at most
    ``limit`` comparisons per key."""

    __slots__ = ("_groups", "_limit")

    def __init__(self, limit: int = MAX_SHARED_HASH) -> None:
        self._groups: dict[bytes, list[Hashable]] = {}
        self._limit = limit

    def add(self, key: Hashable) -> None:
        # The hash as bytes: their hash is seeded, an int's is not.
        group = self._groups.setdefault(hash(key).to_bytes(8, "little", signed=True), [])
        if any(key == other for other in group):
            return
        if len(group) >= self._limit:
            raise HashFlood(f"over {self._limit} distinct keys share one hash")
        group.append(key)


def check_spread(keys: Iterable[Hashable], limit: int = MAX_SHARED_HASH) -> None:
    """Raises ``HashFlood`` when more than ``limit`` distinct ``keys`` share
    one hash."""
    guard = SpreadGuard(limit)
    for key in keys:
        guard.add(key)


__all__ = [
    "MAX_SHARED_HASH",
    "HashFlood",
    "PeerKeyDict",
    "PeerKeySet",
    "SpreadGuard",
    "check_spread",
    "peer_key",
]
