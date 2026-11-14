"""Each placeholder a helper compiles binds the value written there.

A dialect's compiler hooks return their SQL and their parameters separately, so a hook can
place a ``RETURNING`` / ``OUTPUT`` clause before the row values while binding its parameters
after them, or the other way round (Effect #10452: SQL Server bound ``OUTPUT``'s parameters
first). Substituting each parameter into its placeholder must put every value back where the
statement wrote it, for every helper that takes a ``returning`` and every dialect.
"""

import re
from collections.abc import Callable, Sequence

import pytest

import pyfect as fx
from pyfect.sql import mssql, mysql, pg
from pyfect.sql import statement as st

_NUMBERED = re.compile(r"[$@](\d+)")

_COMPILERS = {
    "sqlite": st.make_compiler_sqlite(),
    "pg": pg.make_compiler(),
    "mssql": mssql.make_compiler(),
    "mysql": mysql.make_compiler(),
}


def _literal(value: object) -> str:
    return f"'{value}'" if isinstance(value, str) else str(value)


def _render(sql: str, params: Sequence[object]) -> str:
    """The SQL with each parameter in its placeholder: ``?`` in order, ``$n`` / ``@n`` by
    number."""
    if "?" in sql:
        values = iter(params)
        return re.sub(r"\?", lambda _: _literal(next(values)), sql)
    return _NUMBERED.sub(lambda match: _literal(params[int(match[1]) - 1]), sql)


type _Helper = Callable[[st.Constructor, st.Fragment], object]

_HELPERS: dict[str, tuple[_Helper, str]] = {
    "insert": (
        lambda sql, returning: sql.insert({"name": "Ada", "age": 36}).returning(returning),
        "('Ada',36)",
    ),
    "update": (
        lambda sql, returning: sql.update({"name": "Ada"}).returning(returning),
        "= 'Ada'",
    ),
    "update_values": (
        lambda sql, returning: sql.update_values(
            [{"name": "Ada"}, {"name": "Mira"}], "data"
        ).returning(returning),
        "('Ada'),('Mira')",
    ),
}


@pytest.mark.parametrize("dialect", list(_COMPILERS))
@pytest.mark.parametrize("helper", list(_HELPERS))
def test_every_placeholder_binds_the_value_written_there(dialect: str, helper: str) -> None:
    sql = st.make(fx.never, _COMPILERS[dialect], [], None)
    build, rows = _HELPERS[helper]
    statement = sql("X {} Y {}", build(sql, sql("{} AS source", "audit")), "tail")
    text, params = statement.compile()
    if "AS source" not in text:
        pytest.skip(f"{dialect} has no {helper} helper")
    rendered = _render(text, params)
    assert rows in rendered, rendered
    assert "'audit' AS source" in rendered, rendered
    assert rendered.endswith("Y 'tail'"), rendered
