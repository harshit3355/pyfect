"""(pyfect) The HTTP form of Effect's ``drops queued progress after cancellation``: a request's
progress still waiting for its event stream's reader is dropped once the request is
cancelled, as on stdio and RPC (Effect #10509)."""

from __future__ import annotations

from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred

from ._mcp_http import http_harness, initialize_session, server_layer, sse_reader


@testing.effect
def test_progress_queued_for_an_unread_stream_is_dropped_once_the_request_is_cancelled():
    queued = Deferred[None]()
    cancelled = Deferred[None]()

    def registrations() -> fx.Effect[None, Any, M.McpServer]:
        @fx.gen
        def run():
            server = yield from M.McpServer()

            def handle(_: object) -> fx.Effect[Any]:
                @fx.gen
                def work():
                    for progress in (1, 2):
                        yield from server.notify(
                            "notifications/progress",
                            {"progressToken": "p", "progress": progress},
                        )
                    yield from queued.succeed(None)
                    return (yield from fx.never)

                return work.ensuring(cancelled.succeed(None).as_void())

            tool: Any = {"name": "Work", "inputSchema": {"type": "object"}}
            yield from server.add_tool(ToolEntry(tool, Context.empty(), handle))

        return run

    harness = yield from http_harness(server_layer("A", (P.v2025_11_25,), registrations()))
    headers = yield from initialize_session(harness, P.v2025_11_25)
    call = {
        "jsonrpc": "2.0",
        "id": "work",
        "method": "tools/call",
        "params": {"name": "Work", "arguments": {}, "_meta": {"progressToken": "p"}},
    }
    response = yield from harness.post(call, headers)
    reader = yield from sse_reader(response)
    yield from queued.wait()
    cancel = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": "work"},
    }
    yield from harness.post(cancel, headers)
    yield from cancelled.wait()
    messages = cast("list[Any]", (yield from reader.drain()))
    # The first progress opened the stream before the cancellation; the second waited.
    assert [m["params"]["progress"] for m in messages] == [1]
