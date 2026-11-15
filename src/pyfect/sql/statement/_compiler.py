"""Compilers: from a fragment to SQL text and bound parameters, for one
dialect (Effect's ``Statement.Compiler`` / ``makeCompiler``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from weakref import WeakKeyDictionary

from pyfect.sql.statement._segments import (
    ArrayHelper,
    Custom,
    Fragment,
    Identifier,
    Parameter,
    RecordInsertHelper,
    RecordUpdateHelper,
    RecordUpdateHelperSingle,
    Returning,
)
from pyfect.sql.statement._segments import Literal as LiteralSegment

type Dialect = Literal["sqlite", "pg", "mysql", "mssql", "clickhouse"]

type Compiled = tuple[str, tuple[object, ...]]
"""SQL text and its parameters, in placeholder order."""

type Placeholder = Callable[[object], str]
"""Renders the placeholder of the next parameter."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CompilerOptions:
    """How a dialect renders each part (Effect's ``CompilerOptions``).

    - ``placeholder(index, value)``: the ``index``-th parameter (from 1)
    - ``on_identifier(name, without_transform)``: an escaped name
    - ``on_record_update(placeholders, alias, columns, values, returning)``:
      ``update_values``; ``alias`` is already escaped
    - ``on_custom(segment, placeholder, without_transform)``: a ``Custom``
    - ``on_insert(columns, placeholders, values, returning)`` and
      ``on_record_update_single(columns, values, returning)``: replace the
      default ``INSERT`` / ``UPDATE`` rendering when given
    """

    dialect: Dialect
    placeholder: Callable[[int, object], str]
    on_identifier: Callable[[str, bool], str]
    on_record_update: Callable[
        [str, str, str, Sequence[Sequence[object]], Compiled | None], Compiled
    ]
    on_custom: Callable[[Custom[Any, Any, Any, Any], Placeholder, bool], Compiled]
    on_insert: (
        Callable[[Sequence[str], str, Sequence[Sequence[object]], Compiled | None], Compiled] | None
    ) = None
    on_record_update_single: (
        Callable[[Sequence[str], Sequence[object], Compiled | None], Compiled] | None
    ) = None


_EMPTY_IN_KEYWORD = re.compile(r"\b(NOT\s+)?IN\s*$", re.IGNORECASE)


class _Text:
    """SQL built from appended parts, joined once, so a statement of many
    segments compiles in linear time. It answers ``empty_in`` from the parts
    near its end and offsets it tracks as it grows, never the whole text."""

    __slots__ = ("_last", "_last_dash", "_last_newline", "_newline_before", "_parts", "_starts")

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._starts: list[int] = []
        self._newline_before: list[int] = []
        self._last_newline = -1
        self._last_dash = -1
        """Where the last ``--`` starts."""
        self._last = ""

    def _size(self) -> int:
        return self._starts[-1] + len(self._parts[-1]) if self._parts else 0

    def append(self, text: str) -> None:
        if not text:
            return
        start = self._size()
        self._parts.append(text)
        self._starts.append(start)
        self._newline_before.append(self._last_newline)
        newline = text.rfind("\n")
        if newline >= 0:
            self._last_newline = start + newline
        dash = text.rfind("--")
        if dash >= 0:
            self._last_dash = start + dash
        elif self._last == "-" and text[0] == "-":
            self._last_dash = start - 1
        self._last = text[-1]

    def value(self) -> str:
        return "".join(self._parts)

    def empty_in(self) -> tuple[int, bool] | None:
        """Where a trailing ``IN`` / ``NOT IN`` keyword starts and whether it
        is negated, unless there is none or it is in a ``--`` comment."""
        first = len(self._parts)
        tail = ""
        # The keyword is at most the last two words; a third shows its start.
        while first > 0 and len(tail.split()) < 3:
            first -= 1
            tail = self._parts[first] + tail
        match = _EMPTY_IN_KEYWORD.search(tail)
        if match is None:
            return None
        base = self._starts[first] if self._parts else 0
        newline = tail.rfind("\n", 0, match.start() + 1)
        line_start = base + newline if newline >= 0 else self._newline_before[first]
        # The keyword holds no ``-``, so the last ``--`` is before it.
        if self._last_dash > line_start:
            return None
        return base + match.start(), match.group(1) is not None

    def replace_from(self, start: int, text: str) -> None:
        """Replace everything from ``start`` (in the last part's keyword)."""
        while self._starts[-1] > start:
            self._parts.pop()
            self._starts.pop()
            self._newline_before.pop()
        kept = self._parts[-1][: start - self._starts[-1]]
        self._parts.pop()
        self._starts.pop()
        self._last_newline = self._newline_before.pop()
        self._last = self._parts[-1][-1] if self._parts else ""
        self.append(kept)
        self.append(text)


class Compiler:
    """Compiles fragments for ``dialect``. Results are cached per fragment
    (and per ``without_transform``)."""

    __slots__ = ("_cache", "_cache_no_transform", "_disable_transforms", "_options")

    def __init__(
        self,
        options: CompilerOptions,
        *,
        disable_transforms: bool = False,
        caches: tuple[WeakKeyDictionary[Fragment, Compiled], WeakKeyDictionary[Fragment, Compiled]]
        | None = None,
    ) -> None:
        self._options = options
        self._disable_transforms = disable_transforms
        self._cache, self._cache_no_transform = caches or (WeakKeyDictionary(), WeakKeyDictionary())

    @property
    def dialect(self) -> Dialect:
        return self._options.dialect

    @property
    def options(self) -> CompilerOptions:
        return self._options

    @property
    def without_transform(self) -> Compiler:
        """This compiler, never renaming identifiers."""
        return Compiler(
            self._options,
            disable_transforms=True,
            caches=(self._cache, self._cache_no_transform),
        )

    def compile(self, statement: Fragment, without_transform: bool = False) -> Compiled:
        """``statement``'s SQL and parameters; ``without_transform`` keeps
        identifiers as they are."""
        return self._compile(statement, without_transform, None)

    def _compile(
        self, statement: Fragment, without_transform: bool, override: Placeholder | None
    ) -> Compiled:
        without_transform = without_transform or self._disable_transforms
        cache = self._cache_no_transform if without_transform else self._cache
        if override is None:
            cached = cache.get(statement)
            if cached is not None:
                return cached
        result = _Run(self, without_transform, override).compile(statement)
        if override is None:
            cache[statement] = result
        return result


class _Run:
    """One compilation: the SQL so far, its parameters and the placeholder
    count."""

    __slots__ = ("binds", "compiler", "count", "opts", "placeholder", "sql", "without_transform")

    def __init__(
        self, compiler: Compiler, without_transform: bool, override: Placeholder | None
    ) -> None:
        self.compiler = compiler
        self.opts = compiler.options
        self.without_transform = without_transform
        self.sql = _Text()
        self.binds: list[object] = []
        self.count = 0
        self.placeholder: Placeholder = override or self._next_placeholder

    def _next_placeholder(self, value: object) -> str:
        self.count += 1
        return self.opts.placeholder(self.count, value)

    def _same_placeholder(self, value: object) -> str:
        return self.opts.placeholder(self.count, value)

    def _identifier(self, name: str) -> str:
        return self.opts.on_identifier(name, self.without_transform)

    def _primitive(self, value: object) -> object:
        """The value bound for a record field: a parameter's value, a
        custom segment's first bind, or the value itself."""
        if isinstance(value, Fragment):
            head = value.segments[0]
            if isinstance(head, Custom):
                compiled = self.opts.on_custom(head, self._same_placeholder, self.without_transform)
                return compiled[1][0] if compiled[1] else None
            if isinstance(head, Parameter):
                return head.value
            return None
        return value

    def _returning(self, returning: Returning) -> Compiled | None:
        if isinstance(returning, str):
            return (returning, ())
        if returning is None:
            return None
        return self.compiler._compile(returning, self.without_transform, self.placeholder)  # pyright: ignore[reportPrivateUsage]

    def _columns(self, keys: Sequence[str]) -> str:
        if not keys:
            return "()"
        return "(" + ",".join(self._identifier(key) for key in keys) + ")"

    def _rows(
        self, rows: Sequence[Any], keys: Sequence[str]
    ) -> tuple[str, list[tuple[object, ...]]]:
        """The ``(?,?),(?,?)`` placeholders of ``rows`` and their values."""
        values: list[tuple[object, ...]] = []
        placeholders = ""
        for i, row in enumerate(rows):
            placeholders += "(" if i == 0 else ",("
            items: list[object] = []
            for j, key in enumerate(keys):
                value = row.get(key)
                items.append(self._primitive(value))
                rendered = self.placeholder(value)
                placeholders += rendered if j == 0 else f",{rendered}"
            placeholders += ")"
            values.append(tuple(items))
        return placeholders, values

    def compile(self, statement: Fragment) -> Compiled:
        for segment in statement.segments:
            match segment:
                case LiteralSegment(value, params):
                    self.sql.append(value)
                    if params:
                        self.binds.extend(params)
                case Identifier(value):
                    self.sql.append(self._identifier(value))
                case Parameter(value):
                    self.sql.append(self.placeholder(value))
                    self.binds.append(value)
                case ArrayHelper(value):
                    self._array(value)
                case RecordInsertHelper():
                    self._insert(segment)
                case RecordUpdateHelperSingle():
                    self._update_single(segment)
                case RecordUpdateHelper():
                    self._update(segment)
                case Custom():
                    sql, binds = self.opts.on_custom(
                        segment, self.placeholder, self.without_transform
                    )
                    self.sql.append(sql)
                    self.binds.extend(binds)
        return (self.sql.value(), tuple(self.binds))

    def _array(self, value: tuple[object, ...]) -> None:
        if not value:
            keyword = self.sql.empty_in()
            if keyword is None:
                self.sql.append("()")
            elif self.opts.dialect == "pg":
                # An empty subquery is typed as text in Postgres, so compare
                # with an empty array, which takes the left operand's type.
                start, negated = keyword
                self.sql.replace_from(start, "<> ALL('{}')" if negated else "= ANY('{}')")
            else:
                self.sql.append("(SELECT NULL WHERE 1=0)")
            return
        self.sql.append("(" + ",".join(self.placeholder(v) for v in value) + ")")
        self.binds.extend(value)

    def _insert(self, segment: RecordInsertHelper) -> None:
        keys = list(segment.value[0])
        placeholders, values = self._rows(segment.value, keys)
        if self.opts.on_insert is not None:
            sql, binds = self.opts.on_insert(
                [self._identifier(key) for key in keys],
                placeholders,
                values,
                self._returning(segment.returning_identifier),
            )
            self.sql.append(sql)
            self.binds.extend(binds)
            return
        for row in values:
            self.binds.extend(row)
        self.sql.append(f"{self._columns(keys)} VALUES {placeholders}")
        returning = segment.returning_identifier
        if isinstance(returning, str):
            self.sql.append(f" RETURNING {returning}")
        elif returning is not None:
            sql, binds = cast("Compiled", self._returning(returning))
            self.sql.append(f" RETURNING {sql}")
            self.binds.extend(binds)

    def _update_single(self, segment: RecordUpdateHelperSingle) -> None:
        keys = [key for key in segment.value if key not in segment.omit]
        if self.opts.on_record_update_single is not None:
            sql, binds = self.opts.on_record_update_single(
                [self._identifier(key) for key in keys],
                [self._primitive(segment.value[key]) for key in keys],
                self._returning(segment.returning_identifier),
            )
            self.sql.append(sql)
            self.binds.extend(binds)
            return
        for i, key in enumerate(keys):
            value = segment.value[key]
            assignment = f"{self._identifier(key)} = {self.placeholder(value)}"
            self.sql.append(assignment if i == 0 else f", {assignment}")
            self.binds.append(self._primitive(value))
        returning = segment.returning_identifier
        mssql = self.opts.dialect == "mssql"
        if isinstance(returning, str):
            if mssql:
                self.sql.append(f" OUTPUT {'INSERTED.*' if returning == '*' else returning}")
            else:
                self.sql.append(f" RETURNING {returning}")
        elif returning is not None:
            self.sql.append(" OUTPUT " if mssql else " RETURNING ")
            sql, binds = cast("Compiled", self._returning(returning))
            self.sql.append(sql)
            self.binds.extend(binds)

    def _update(self, segment: RecordUpdateHelper) -> None:
        keys = list(segment.value[0])
        placeholders, values = self._rows(segment.value, keys)
        sql, binds = self.opts.on_record_update(
            placeholders,
            self.opts.on_identifier(segment.alias, True),
            self._columns(keys),
            values,
            self._returning(segment.returning_identifier),
        )
        self.sql.append(sql)
        self.binds.extend(binds)


def make_compiler(
    *,
    dialect: Dialect,
    placeholder: Callable[[int, object], str],
    on_identifier: Callable[[str, bool], str],
    on_record_update: Callable[
        [str, str, str, Sequence[Sequence[object]], Compiled | None], Compiled
    ],
    on_custom: Callable[[Custom[Any, Any, Any, Any], Placeholder, bool], Compiled],
    on_insert: Callable[[Sequence[str], str, Sequence[Sequence[object]], Compiled | None], Compiled]
    | None = None,
    on_record_update_single: Callable[[Sequence[str], Sequence[object], Compiled | None], Compiled]
    | None = None,
) -> Compiler:
    """A compiler for ``dialect`` from its rendering callbacks (see
    ``CompilerOptions``)."""
    return Compiler(
        CompilerOptions(
            dialect=dialect,
            placeholder=placeholder,
            on_identifier=on_identifier,
            on_record_update=on_record_update,
            on_custom=on_custom,
            on_insert=on_insert,
            on_record_update_single=on_record_update_single,
        )
    )


def default_escape(c: str) -> Callable[[str], str]:
    """Escape names with the quote ``c``: wrapped in it, ``c`` doubled, and
    each dot a boundary between quoted parts (``a.b`` is ``"a"."b"``)."""
    double = c + c
    dot = c + "." + c

    def escape(name: str) -> str:
        return c + name.replace(c, double).replace(".", dot) + c

    return escape


_escape_sqlite = default_escape('"')


def _nothing(*_args: object) -> Compiled:
    return ("", ())


def make_compiler_sqlite(transform: Callable[[str], str] | None = None) -> Compiler:
    """SQLite's compiler: ``?`` placeholders and ``"quoted"`` names, renamed
    with ``transform`` unless a statement runs without transforms."""

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return _escape_sqlite(value)
        return _escape_sqlite(transform(value))

    return make_compiler(
        dialect="sqlite",
        placeholder=lambda _index, _value: "?",
        on_identifier=on_identifier,
        on_record_update=_nothing,
        on_custom=_nothing,
    )


__all__ = [
    "Compiled",
    "Compiler",
    "CompilerOptions",
    "Dialect",
    "Placeholder",
    "default_escape",
    "make_compiler",
    "make_compiler_sqlite",
]
