"""Every shape the structured-output codecs rewrite survives being an optional key.

``to_codec_openai`` and ``to_codec_anthropic`` rewrite tuples, records and unions, and turn an
optional key into a required nullable one. An optional key's decoded side must be its schema's
type side, not the rewritten encoded form (Effect #10502), and a schema that already accepts
``null`` gets one ``null`` branch (#10522). Each shape below is checked required and optional,
through both codecs: a present value round-trips, an absent key is sent as ``null`` and decoded
back to absent. Add a row for each shape the rewrite learns.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.testing import SchemaAsserts


class _Required(TypedDict):
    value: Any


class _Optional(TypedDict):
    value: NotRequired[Any]


class _Inner(TypedDict):
    tags: dict[str, float]
    pair: NotRequired[tuple[str, float]]


_SHAPES: list[tuple[str, S.Codec[Any, Any], object]] = [
    ("Finite", S.Finite, 1),
    ("NullOr(Finite)", S.NullOr(S.Finite), 1),
    ("Tuple", S.Tuple(S.String, S.Finite), ("a", 1)),
    ("TupleWithRest", S.TupleWithRest(S.Tuple(S.String), S.Finite), ("a", 1, 2)),
    ("Record", S.Record(S.String, S.Finite), {"a": 1}),
    ("NullOr(Record)", S.NullOr(S.Record(S.String, S.Finite)), {"a": 1}),
    ("Union(String, Tuple)", S.Union(S.String, S.Tuple(S.String, S.Finite)), ("a", 1)),
    ("Array(Tuple)", S.Array(S.Tuple(S.String, S.Finite)), (("a", 1),)),
    (
        "Struct(Record, optional Tuple)",
        S.Struct(_Inner, tags=S.Record(S.String, S.Finite), pair=S.Tuple(S.String, S.Finite)),
        {"tags": {"a": 1}, "pair": ("a", 1)},
    ),
]

_CODECS: list[tuple[str, Callable[[S.Codec[Any, Any]], Any]]] = [
    ("openai", to_codec_openai),
    ("anthropic", to_codec_anthropic),
]


@pytest.mark.parametrize(("provider", "to_codec"), _CODECS, ids=[c[0] for c in _CODECS])
@pytest.mark.parametrize(("shape", "schema", "value"), _SHAPES, ids=[s[0] for s in _SHAPES])
def test_required_value_round_trips(
    provider: str,
    to_codec: Callable[[S.Codec[Any, Any]], Any],
    shape: str,
    schema: S.Codec[Any, Any],
    value: object,
) -> None:
    codec = to_codec(S.Struct(_Required, value=schema)).codec
    encoded = S.encode_unknown_sync(codec)({"value": value})
    assert S.decode_unknown_sync(codec)(encoded) == {"value": value}


@pytest.mark.parametrize(("provider", "to_codec"), _CODECS, ids=[c[0] for c in _CODECS])
@pytest.mark.parametrize(("shape", "schema", "value"), _SHAPES, ids=[s[0] for s in _SHAPES])
def test_optional_value_round_trips_and_absent_is_null(
    provider: str,
    to_codec: Callable[[S.Codec[Any, Any]], Any],
    shape: str,
    schema: S.Codec[Any, Any],
    value: object,
) -> None:
    result = to_codec(S.Struct(_Optional, value=schema))
    encoded = S.encode_unknown_sync(result.codec)({"value": value})
    assert S.decode_unknown_sync(result.codec)(encoded) == {"value": value}
    asserts = SchemaAsserts(result.codec)
    asserts.encoding().succeed({}, {"value": None})
    asserts.decoding().succeed({"value": None}, {})
    branches = result.json_schema["properties"]["value"].get("anyOf", [])
    assert branches.count({"type": "null"}) <= 1
