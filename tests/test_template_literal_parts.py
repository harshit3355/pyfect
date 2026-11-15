"""Every kind of node a template literal accepts as a part works in every derivation.

The kinds of part are listed in several places (the part check, segment matching, reading a
segment's value, the JSON Schema pattern, the strategy, representations). Effect main (#10576)
found `Enum` missing from them; this table holds one part of each kind, so a kind added to the
part check without the rest fails here.
"""

from __future__ import annotations

import enum
import re
from typing import Any

import pytest
from hypothesis import find, given, settings
from hypothesis import strategies as st

from pyfect import schema as S
from pyfect.schema import representation as R
from pyfect.schema.ast._template_literal import PART_KINDS


class _Mixed(enum.Enum):
    Task = "task"
    One = 1


_PARTS: dict[str, Any] = {
    "String": S.String,
    "Number": S.Finite,
    "BigInt": S.BigInt,
    "Literal": S.Literal("a.b"),
    "Enum": S.Enum(_Mixed),
    "TemplateLiteral": S.TemplateLiteral("x", S.Finite),
    "Union": S.Union(S.Literal("u"), S.Enum(_Mixed)),
}


def test_the_table_has_every_kind_the_part_check_accepts() -> None:
    assert {kind.__name__ for kind in PART_KINDS} == set(_PARTS)
    for kind, part in _PARTS.items():
        assert type(part.__codec__().ast).__name__ == kind


@pytest.mark.parametrize("kind", list(_PARTS))
@settings(max_examples=20, derandomize=True, database=None, deadline=None)
@given(data=st.data())
def test_a_part_works_in_every_derivation(kind: str, data: st.DataObject) -> None:
    part = _PARTS[kind]
    template = S.TemplateLiteral("<", part, ">")
    text = data.draw(S.to_strategy(template))
    assert S.is_(template)(text)

    pattern = S.to_json_schema_document(template).schema["pattern"]
    assert isinstance(pattern, str)
    assert re.search(pattern, text), (pattern, text)

    revived = R.from_representation(R.to_representation(template), revivers=R.BUILTIN_REVIVERS)
    assert S.is_(revived)(text)

    parser = S.TemplateLiteralParser("<", part, ">")
    values = S.decode_sync(parser)(text)
    assert S.encode_sync(parser)(values) == text


def test_the_strategy_draws_every_enum_member() -> None:
    strategy = S.to_strategy(S.TemplateLiteral(S.Enum(_Mixed)))
    for member in _Mixed:
        text = str(member.value)
        assert find(strategy, lambda drawn, text=text: drawn == text) == text
