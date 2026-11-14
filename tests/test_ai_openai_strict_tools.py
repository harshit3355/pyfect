"""OpenAI and OpenAI-compatible tools are decoded with the codec they were advertised with.

A strict tool is advertised with ``to_codec_openai``'s JSON Schema (a record as an array of
``[key, value]`` pairs), so its calls are decoded back through that codec; a non-strict one is
advertised with the default codec's JSON Schema, so its calls are taken as sent (Effect #10533).
``StrictTools`` (``pyfect.ai._provider_tools``) makes both decisions; here each provider, strict
mode and response path (generate and stream) sends the arguments its advertised schema asks for
and must hand the tool the same record.
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
import json
from typing import Any, TypedDict

import pytest
from oracle import test_ai_openai_language_model as openai_oracle
from oracle import test_openai_compat_language_model as compat_oracle
from oracle._ai_http import mock_json, mock_sse

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K


class Tags(TypedDict):
    tags: dict[str, str]


Tagger = T.make("Tagger", parameters=S.Struct(Tags, tags=S.Record(S.String, S.String)))
_TOOLKIT = K.make(Tagger)
_DECODED = {"tags": {"a": "b"}}
_ARGS = {True: {"tags": [{"0": "a", "1": "b"}]}, False: _DECODED}
_RECORD_SCHEMA = {
    True: "array",
    False: "object",
}


def _openai(strict: bool, streaming: bool) -> fx.Effect[tuple[Any, list[Any]], Any, Any]:
    args = _ARGS[strict]
    config = {"strict_json_schema": strict}
    options: dict[str, Any] = {
        "prompt": "Tag",
        "toolkit": _TOOLKIT,
        "disable_tool_call_resolution": True,
    }
    if streaming:
        events = openai_oracle._function_events("Tagger", json.dumps(args))  # pyright: ignore[reportPrivateUsage]
        return openai_oracle._stream_parts(events, config=config, **options).map(  # pyright: ignore[reportPrivateUsage]
            lambda parts: (None, parts)
        )
    mock = mock_json(
        openai_oracle.response_body(output=[openai_oracle.function_call("Tagger", args)])
    )
    run = lm.generate_text(**options).map(lambda r: list(r.content))
    return openai_oracle._provided(run, mock, "gpt-4o-mini", config).map(  # pyright: ignore[reportPrivateUsage]
        lambda parts: (mock.bodies[0]["tools"][0]["parameters"], parts)
    )


def _compat(strict: bool, streaming: bool) -> fx.Effect[tuple[Any, list[Any]], Any, Any]:
    arguments = json.dumps(_ARGS[strict])
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "Tagger", "arguments": arguments},
    }
    config = {"strict_json_schema": strict}
    options: dict[str, Any] = {"toolkit": _TOOLKIT, "disable_tool_call_resolution": True}
    if streaming:
        events = [
            compat_oracle.chunk("chatcmpl_1", {"tool_calls": [{"index": 0, **call}]}, "tool_calls"),
            "[DONE]",
        ]
        mock = mock_sse(events)
        run: Any = lm.stream_text("Tag", **options).run_collect()
    else:
        message = {"content": None, "tool_calls": [call]}
        mock = mock_json(compat_oracle.completion(message, finish_reason="tool_calls"))
        run = lm.generate_text("Tag", **options).map(lambda r: list(r.content))
    return compat_oracle._provided(run, mock, "gpt-4o-mini", config).map(  # pyright: ignore[reportPrivateUsage]
        lambda parts: (mock.bodies[0]["tools"][0]["function"]["parameters"], parts)
    )


@pytest.mark.parametrize("streaming", [False, True], ids=["generate", "stream"])
@pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
@pytest.mark.parametrize("provider", [_openai, _compat], ids=["openai", "openai-compat"])
@testing.effect
def test_calls_decode_with_the_advertised_codec(provider: Any, strict: bool, streaming: bool):
    advertised, parts = yield from provider(strict, streaming)
    if advertised is not None:
        assert advertised["properties"]["tags"]["type"] == _RECORD_SCHEMA[strict]
    call = next(p for p in parts if isinstance(p, R.ToolCallPart))
    assert call.params == _DECODED
