r"""Parameters as literals in a text-protocol statement, as mysql2 (sql-escaper) writes
them, in the session's quoting mode.

Every piece of text goes through one function that knows the mode: under
``NO_BACKSLASH_ESCAPES`` a backslash is plain text and only ``'`` is doubled, so a
backslash escape would end the literal early. asyncmy's ``escape`` follows the mode for a
top-level ``str`` only (bytes, a tuple's items and its fallback for other types are always
backslash-escaped), so it is used here only for the types whose literal holds no text.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import cast

from asyncmy.converters import escape_item  # pyright: ignore[reportUnknownVariableType]
from asyncmy.converters import (
    escape_string as _backslash_escaped,  # pyright: ignore[reportUnknownVariableType]
)

from pyfect import _json_text as json_text

type Literal = Callable[[object, bool], str]
"""A parameter's literal; the flag says whether a dict there is a ``SET`` assignment list."""

_FORMATTED = frozenset(
    (
        bool,
        int,
        float,
        Decimal,
        dt.date,
        dt.datetime,
        dt.time,
        dt.timedelta,
    )
)
"""The types asyncmy writes as numbers or fixed date and time text."""


def identifier(name: str) -> str:
    """sql-escaper's ``escapeId``: a dot qualifies the name, unless it holds a JSON
    operator (``->``)."""
    quoted = name.replace("`", "``")
    if "->" not in name:
        quoted = quoted.replace(".", "`.`")
    return f"`{quoted}`"


def text_literal(*, no_backslash_escapes: bool) -> Literal:
    r"""Literals for a session in the given mode: text quoted for it, bytes as
    ``X'hex'`` (mysql2's Buffer), a tuple as ``(a, b)``, a list as ``a, b`` (a list in it
    ``(a, b)``), a dict in a ``SET`` assignment list as ``\`key\` = value`` pairs and
    elsewhere as its JSON text (where mysql2 writes ``'[object Object]'``); any other
    value is its ``str`` as text."""

    return _Literals(no_backslash_escapes).literal


class _Literals:
    """``text_literal``'s writer for one quoting mode; methods rather than closures
    calling each other, which would be a reference cycle."""

    __slots__ = ("no_backslash_escapes",)

    def __init__(self, no_backslash_escapes: bool) -> None:
        self.no_backslash_escapes = no_backslash_escapes

    def text(self, value: str) -> str:
        if self.no_backslash_escapes:
            return "'" + value.replace("'", "''") + "'"
        return "'" + _backslash_escaped(value) + "'"

    def value(self, item: object) -> str:  # noqa: PLR0911
        if item is None:
            return "NULL"
        if type(item) in _FORMATTED:
            return cast("str", escape_item(item, "utf8mb4"))
        if isinstance(item, (bytes, bytearray)):
            return f"X'{bytes(item).hex()}'"
        if isinstance(item, list):
            return self.listed(cast("list[object]", item))
        if isinstance(item, tuple):
            return "(" + ",".join(self.value(x) for x in cast("tuple[object, ...]", item)) + ")"
        if isinstance(item, (set, frozenset)):
            return ",".join(self.value(x) for x in cast("set[object]", item))
        if isinstance(item, dict):
            return self.text(json_text.stringify(cast("object", item)))
        return self.text(str(item))

    def listed(self, items: list[object]) -> str:
        return ", ".join(
            f"({self.listed(cast('list[object]', item))})"
            if isinstance(item, list)
            else self.value(item)
            for item in items
        )

    def literal(self, param: object, assigns: bool) -> str:
        if assigns and isinstance(param, dict):
            pairs = cast("dict[object, object]", param).items()
            return ", ".join(f"{identifier(str(key))} = {self.value(item)}" for key, item in pairs)
        return self.value(param)


__all__ = ["Literal", "identifier", "text_literal"]
