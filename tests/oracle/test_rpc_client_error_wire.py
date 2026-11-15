"""``RpcClientError`` encodes as Effect 4.1.2's does.

Each expected value is what Effect 4.1.2 printed for
``Schema.encodeUnknownSync(Schema.toCodecJson(RpcClientError))`` of the
same error (causes there were ``new Error(...)``, so the causes here are an
exception class named ``Error``)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeAliasType, cast, get_args

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.http import client as http_client
from pyfect.http import request
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError, HttpClientErrorSchema, TransportError
from pyfect.rpc import RpcClientDefect, RpcClientError, RpcGroup, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc.client_error import RpcClientErrorReason
from pyfect.socket import (
    SocketCloseError,
    SocketError,
    SocketOpenError,
    SocketReadError,
    SocketUpgradeError,
    SocketWriteError,
)
from pyfect.workers.worker_error import WorkerSpawnError


class Error(Exception):
    """Named as JavaScript's ``Error``, so a defect encodes as Effect's."""


def _http() -> HttpClientError:
    return HttpClientError(TransportError(request.get("http://x"), cause=Error("boom")))


_CASES: list[tuple[str, RpcClientError, object]] = [
    (
        "http",
        RpcClientError(reason=HttpClientErrorSchema.from_http_client_error(_http())),
        {
            "_tag": "RpcClientError",
            "reason": {
                "_tag": "HttpError",
                "kind": "TransportError",
                "cause": {
                    "name": "TransportError",
                    "message": "Transport error (GET http://x)",
                    "cause": {"name": "Error", "message": "boom"},
                },
            },
        },
    ),
    (
        "http without a cause",
        RpcClientError(reason=HttpClientErrorSchema(kind="StatusCodeError")),
        {"_tag": "RpcClientError", "reason": {"_tag": "HttpError", "kind": "StatusCodeError"}},
    ),
    (
        "close",
        RpcClientError(reason=SocketCloseError(code=1006)),
        {"_tag": "RpcClientError", "reason": {"_tag": "SocketCloseError", "code": 1006}},
    ),
    (
        "close with a reason",
        RpcClientError(reason=SocketCloseError(code=1000, close_reason="bye")),
        {
            "_tag": "RpcClientError",
            "reason": {"_tag": "SocketCloseError", "code": 1000, "closeReason": "bye"},
        },
    ),
    (
        "open",
        RpcClientError(reason=SocketOpenError(kind="Timeout", cause=Error("t"))),
        {
            "_tag": "RpcClientError",
            "reason": {
                "_tag": "SocketOpenError",
                "kind": "Timeout",
                "cause": {"name": "Error", "message": "t"},
            },
        },
    ),
    (
        "read",
        RpcClientError(reason=SocketReadError(cause="x")),
        {"_tag": "RpcClientError", "reason": {"_tag": "SocketReadError", "cause": "x"}},
    ),
    (
        "upgrade",
        RpcClientError(reason=SocketUpgradeError()),
        {"_tag": "RpcClientError", "reason": {"_tag": "SocketUpgradeError"}},
    ),
    (
        "defect",
        RpcClientError(reason=RpcClientDefect(message="bad", cause=Error("c"))),
        {
            "_tag": "RpcClientError",
            "reason": {
                "_tag": "RpcClientDefect",
                "message": "bad",
                "cause": {"name": "Error", "message": "c"},
            },
        },
    ),
    (
        "worker",
        RpcClientError(reason=WorkerSpawnError(message="m")),
        {"_tag": "RpcClientError", "reason": {"_tag": "WorkerSpawnError", "message": "m"}},
    ),
]

_CODEC = S.to_codec_json(RpcClientError)


@pytest.mark.parametrize(("error", "expected"), [c[1:] for c in _CASES], ids=[c[0] for c in _CASES])
def test_encodes_as_effect_does(error: RpcClientError, expected: object) -> None:
    assert json.loads(json.dumps(S.encode_unknown_sync(_CODEC)(error))) == expected


@pytest.mark.parametrize("expected", [c[2] for c in _CASES], ids=[c[0] for c in _CASES])
def test_decodes_what_effect_encodes(expected: object) -> None:
    decoded = S.decode_unknown_sync(_CODEC)(expected)
    assert isinstance(decoded, RpcClientError)
    assert S.encode_unknown_sync(_CODEC)(decoded) == expected


def test_messages_are_effects() -> None:
    assert RpcClientError(reason=SocketCloseError(code=1006)).message == "SocketCloseError: 1006"
    assert HttpClientErrorSchema.from_http_client_error(_http()).message == (
        "Transport error (GET http://x)"
    )
    assert RpcClientError(reason=RpcClientDefect(message="bad")).message == "RpcClientDefect: bad"


def test_the_http_reason_keeps_the_http_reason_as_its_cause() -> None:
    error = _http()
    schema = HttpClientErrorSchema.from_http_client_error(error)
    assert (schema.kind, schema.cause) == ("TransportError", error.reason)


def test_a_socket_error_encodes_its_reason() -> None:
    error = SocketError(reason=SocketOpenError(kind="Unknown", cause="refused", target="h:1"))
    encoded = S.encode_unknown_sync(S.to_codec_json(SocketError))(error)
    assert encoded == {
        "_tag": "SocketError",
        "reason": {
            "_tag": "SocketOpenError",
            "kind": "Unknown",
            "cause": "refused",
            "target": "h:1",
        },
    }
    assert error.cause == "refused"


class _Echo(RpcGroup):
    ping = make("Ping", success=S.String)


def test_an_http_protocol_fails_with_the_http_error_as_its_schema() -> None:
    transport = TransportError(request.get("http://localhost/rpc"), cause=Error("refused"))

    def send(*_: object) -> fx.Effect[Any, HttpClientError]:
        return fx.fail(HttpClientError(transport))

    protocol = (
        rpc_client.layer_protocol_http("http://localhost/rpc")
        .pipe(layer.provide_merge(rs.layer_ndjson))
        .pipe(layer.provide_merge(layer.succeed(HttpClient, http_client.make(send))))
    )

    def body():
        client = yield from rpc_client.make(_Echo, layer=protocol)
        return (yield from client.ping().exit())

    exit = fx.run_blocking(fx.scoped(effect.gen(body)).timeout("5 seconds").or_die())
    assert isinstance(exit, Exit.Failure)
    assert exit.cause.squash() == RpcClientError(
        reason=HttpClientErrorSchema(kind="TransportError", cause=transport)
    )


def _reason_classes() -> list[type[Any]]:
    def flat(t: object) -> list[type[Any]]:
        value = t.__value__ if isinstance(t, TypeAliasType) else t
        args = get_args(value)
        return [c for arg in args for c in flat(arg)] if args else [cast("type[Any]", value)]

    return flat(RpcClientErrorReason)


# Reasons whose message is a field the caller fills.
_MESSAGE_GIVEN = {
    "WorkerSpawnError",
    "WorkerSendError",
    "WorkerReceiveError",
    "WorkerUnknownError",
    "RpcClientDefect",
}

# The least each other reason can be made with.
_MINIMAL: dict[str, Callable[[], Any]] = {
    "SocketReadError": lambda: SocketReadError(cause=None),
    "SocketWriteError": lambda: SocketWriteError(cause=None),
    "SocketOpenError": lambda: SocketOpenError(kind="Unknown", cause=None),
    "SocketUpgradeError": lambda: SocketUpgradeError(cause=None),
    "SocketCloseError": lambda: SocketCloseError(code=1006),
    "HttpClientErrorSchema": lambda: HttpClientErrorSchema(kind="TransportError"),
}


def test_every_reason_says_what_failed_in_the_rpc_client_error_message() -> None:
    """Effect #10496: an HTTP failure's ``RpcClientError`` said only ``HttpError: ``. Every reason
    of the union that makes its own message (read from the union, so a new one must be listed
    here) names what failed after the tag, even when made with nothing to say."""
    names = sorted(c.__name__ for c in _reason_classes())
    assert names == sorted([*_MINIMAL, *_MESSAGE_GIVEN])
    for name, make_reason in _MINIMAL.items():
        tag, said = RpcClientError(reason=make_reason()).message.split(": ", 1)
        assert tag and said.strip(), name
