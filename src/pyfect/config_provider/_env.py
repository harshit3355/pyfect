"""``from_env`` and ``from_env_record``: flat ``NAME=value`` pairs read as a
tree, each ``_`` in a name starting a new path segment."""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping

from pyfect._core import Effect
from pyfect._digits import parse_digits
from pyfect.config_provider._node import Array, Keys, Node, Path, Record, SourceError, Value
from pyfect.config_provider._provider import ConfigProvider, make
from pyfect.effect import succeed, suspend

_MAX_INDEX = 2**32 - 1


type _Trie = dict[str, _Trie]
"""Name segments below a path; empty when no name continues past it."""


def from_env_record(
    env: Mapping[str, str | None], *, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """A provider over ``env``; ``None`` values are skipped. A name is split
    on every ``_`` (``A__B`` has an empty middle segment), and a path also
    matches the name its segments join to, so ``("NODE_ENV",)`` and
    ``("NODE", "ENV")`` both find ``NODE_ENV``. A path whose children are
    all array indices (``A_0``, ``A_1``) is an ``Array``; one with other
    children a ``Record``, holding the path's own value if it has one. An
    empty value is absent unless ``preserve_empty_strings``. As in Effect,
    the names are read when the provider is made and the values at each
    lookup."""
    trie = _trie(env)
    return make(lambda path: succeed(_node_at(trie, env, path, preserve_empty_strings)))


def from_env(
    env: Mapping[str, str] | None = None, *, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """``from_env_record`` over ``env``, or over a copy of ``os.environ``.

    As in Effect, that copy is made when the first lookup runs, not when the
    provider is made, and every later lookup, also through providers derived
    with ``map_input``, ``nested`` or ``constant_case``, reuses it: later
    writes to the environment are not seen. Use
    ``from_env_record(dict(os.environ))`` to take the copy at a chosen
    moment."""
    if env is not None:
        return from_env_record(env, preserve_empty_strings=preserve_empty_strings)
    return make(_EnvironmentSnapshot(preserve_empty_strings).load)


class _EnvironmentSnapshot:
    """``os.environ`` copied at the first lookup."""

    __slots__ = ("_lock", "_preserve_empty_strings", "_provider")

    def __init__(self, preserve_empty_strings: bool) -> None:
        self._preserve_empty_strings = preserve_empty_strings
        self._provider: ConfigProvider | None = None
        self._lock = threading.Lock()

    def load(self, path: Path) -> Effect[Node | None, SourceError]:
        return suspend(lambda: self._snapshot().load(path))

    def _snapshot(self) -> ConfigProvider:
        with self._lock:
            if self._provider is None:
                self._provider = from_env_record(
                    dict(os.environ), preserve_empty_strings=self._preserve_empty_strings
                )
            return self._provider


def _trie(env: Mapping[str, str | None]) -> _Trie:
    root: _Trie = {}
    for name, value in env.items():
        if value is None:
            continue
        node = root
        for segment in name.split("_"):
            node = node.setdefault(segment, {})
    return root


def _node_at(
    trie: _Trie, env: Mapping[str, str | None], path: Path, preserve_empty_strings: bool
) -> Node | None:
    leaf = env.get("_".join(str(seg) for seg in path))
    if leaf == "" and not preserve_empty_strings:
        leaf = None
    node: _Trie | None = trie
    for seg in path:
        node = node.get(str(seg))
        if node is None:
            break
    if not node:
        return None if leaf is None else Value(leaf)
    if all(_is_index(child) for child in node):
        return Array(max(int(child) for child in node) + 1, leaf)
    return Record(Keys(node), leaf)


def _is_index(key: str) -> bool:
    index = parse_digits(key, unpadded=True)
    return index is not None and index < _MAX_INDEX
