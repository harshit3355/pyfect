"""Messages a transport hands the RPC server before it runs (``with_run``'s
buffer) are replayed one by one: a bad one fails only itself."""

from typing import Any

import pytest

import pyfect as fx
from pyfect import effect
from pyfect import schema as S
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.server._protocol import Message


class Echo(RpcGroup):
    echo = make("echo", payload=S.String, success=S.String)
    wait = make("wait", payload=S.String, success=S.String)


ECHO: Message = {"_tag": "Request", "id": "1", "tag": "echo", "payload": "hi", "headers": []}


def _serve_after(early: list[tuple[int, Message]], late: list[tuple[int, Message]]) -> list[Any]:
    """Writes ``early`` before the server runs and ``late`` once it does;
    returns everything the server sent, as ``(client_id, message)``."""
    sent: list[Any] = []

    def body():
        disconnects = yield from fx.Queue[int].unbounded()
        writers: list[Any] = []

        def parts(write: Any) -> fx.Effect[rpc_server.ProtocolParts]:
            writers.append(write)
            return effect.succeed(
                rpc_server.ProtocolParts(
                    disconnects=disconnects,
                    send=lambda client_id, message: effect.sync(
                        lambda: sent.append((client_id, dict(message)))
                    ),
                    end=lambda _id: effect.void,
                    supports_ack=False,
                    supports_span_propagation=False,
                    codec_for=rs.json.codec_for,
                )
            )

        protocol = yield from rpc_server.with_run(parts)
        for client_id, message in early:
            yield from writers[0](client_id, message)
        handlers = Echo.to_layer(
            Echo.handlers()
            .handle(Echo.echo)(lambda r: fx.succeed(r.payload))
            .handle(Echo.wait)(lambda _: effect.never)
        )
        yield from (
            rpc_server.make(Echo)
            .pipe(effect.provide_service(rpc_server.ServerProtocol, protocol))
            .pipe(fx.provide(handlers))
            .fork_scoped()
        )
        for _ in range(5):
            yield from effect.yield_now()
        for client_id, message in late:
            yield from writers[0](client_id, message).exit()
        for _ in range(5):
            yield from effect.yield_now()

    fx.run_blocking(fx.scoped(effect.gen(body)).timeout("5 seconds").or_die())
    return sent


def _answered(sent: list[Any], client_id: int) -> bool:
    return any(
        c == client_id and m.get("_tag") == "Exit" and m["exit"].get("value") == "hi"
        for c, m in sent
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"_tag": "Interrupt"},
        {"_tag": "Ack"},
        {"_tag": "Interrupt", "requestId": None},
        {"_tag": "Ack", "requestId": True},
        {"_tag": "Interrupt", "requestId": ["1"]},
    ],
)
def test_a_control_message_without_a_valid_request_id_fails_only_its_client(bad: Message) -> None:
    sent = _serve_after([(1, bad), (2, ECHO)], [(3, ECHO), (1, bad)])
    assert _answered(sent, 2)
    assert _answered(sent, 3)
    defects = [m for c, m in sent if c == 1 and m.get("_tag") == "Defect"]
    assert len(defects) == 2


def test_a_buffered_request_reusing_a_running_id_does_not_stop_the_server() -> None:
    wait: Message = {**ECHO, "tag": "wait"}
    sent = _serve_after([(1, wait), (1, wait), (2, ECHO)], [(3, ECHO)])
    assert _answered(sent, 2)
    assert _answered(sent, 3)


def _post_http(body: str, *, timeout: float = 10.0) -> str:
    import asyncio

    from pyfect import layer
    from pyfect.http import router
    from pyfect.http.web import WebRequest

    handlers = Echo.to_layer(
        Echo.handlers()
        .handle(Echo.echo)(lambda r: fx.succeed(r.payload))
        .handle(Echo.wait)(lambda _: effect.never)
    )
    app = (
        rpc_server.layer_http(Echo, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_ndjson))
    )
    out: list[str] = []

    async def main() -> None:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            request = WebRequest("http://test/rpc", method="POST", body=body)
            response = await asyncio.wait_for(made.handler(request), timeout)
            out.append(await asyncio.wait_for(response.text(), timeout))
        finally:
            await made.dispose()

    asyncio.run(main())
    return out[0]


def test_http_answers_a_body_of_more_inline_failures_than_its_stream_buffer() -> None:
    import json

    lines = [
        json.dumps({"_tag": "Request", "id": str(i), "tag": "nope", "payload": "", "headers": []})
        for i in range(40)
    ]
    text = _post_http("\n".join(lines) + "\n")
    assert text.count('"_tag":"Exit"') == 40


def test_http_a_request_without_an_id_fails_only_itself() -> None:
    text = _post_http(
        '{"_tag":"Request","tag":"echo","payload":"x","headers":[]}\n'
        '{"_tag":"Interrupt"}\n'
        '{"_tag":"Request","id":"1","tag":"echo","payload":"hi","headers":[]}\n'
    )
    assert '"value":"hi"' in text
