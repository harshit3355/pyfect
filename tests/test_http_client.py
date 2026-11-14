"""The HTTP client beyond Effect's tests: ``layer_test``, aborting unread
responses, and the httpx backend cancelling requests."""

import gc
import sys
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from _threads import live_threads

import pyfect as fx
from pyfect import testing
from pyfect.http import client as c
from pyfect.http import cookies
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http.abort import AbortSignal
from pyfect.http.error import HttpClientError


def _run[A](eff: fx.Effect[A, object]) -> A:
    return fx.run_blocking(eff.or_die())


@testing.effect
def test_layer_test_answers_with_the_handler():
    def handle(
        request: req.HttpClientRequest,
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        return fx.succeed(res.make(request, f"{request.method} {request.url}"))

    text = (
        yield from c.get("http://test/path")
        .flat_map(lambda r: r.text)
        .pipe(fx.provide(c.layer_test(handle)))
    )
    assert text == "GET http://test/path"


def test_unread_response_is_aborted_when_collected() -> None:
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "unread"))

    _run(c.make(send).get("http://test/").as_void())
    gc.collect()
    assert signals[0].aborted


def test_unread_response_is_aborted_as_soon_as_it_is_dropped() -> None:
    """Without waiting for the cycle collector: a response kept in a reference
    cycle stays open until a collection, so a server shutting down waits for
    its connection."""
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "unread"))

    gc.disable()
    try:
        _run(c.make(send).get("http://test/").as_void())
        assert signals[0].aborted
    finally:
        gc.enable()


def test_a_read_response_stays_readable() -> None:
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "body"))

    reads = c.make(send).get("http://test/").flat_map(lambda r: r.text.zip(r.text))
    assert _run(reads) == ("body", "body")
    assert not signals[0].aborted


class _Hanging(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    closed = threading.Event()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/body":
            self.send_response(200)
            self.send_header("content-length", "4")
            self.end_headers()
            self.wfile.write(b"test")
            return
        self.connection.recv(1)
        type(self).closed.set()
        self.close_connection = True


@pytest.fixture
def hanging_server() -> Iterator[str]:
    _Hanging.closed.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hanging)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_httpx_interrupt_closes_the_connection(hanging_server: str) -> None:
    pytest.importorskip("httpx")
    from pyfect.http import httpx_client

    timed_out = _run(
        c.get(f"{hanging_server}/hang")
        .timeout("200 millis")
        .option()
        .pipe(fx.provide(httpx_client.layer))
    )
    assert timed_out is None
    assert _Hanging.closed.wait(2)


def _wait_for_loop_threads() -> None:
    for thread in live_threads("pyfect-httpx"):
        thread.join(2)


def test_httpx_unread_response_after_the_layer_closed(hanging_server: str) -> None:
    pytest.importorskip("httpx")
    from pyfect.http import httpx_client

    unraisable: list[Any] = []
    previous = sys.unraisablehook
    sys.unraisablehook = unraisable.append
    try:
        response = _run(c.get(f"{hanging_server}/body").pipe(fx.provide(httpx_client.layer)))
        assert response.status == 200
        _wait_for_loop_threads()
        del response
        gc.collect()
    finally:
        sys.unraisablehook = previous
    assert unraisable == []


def _never_sending(
    signals: list[AbortSignal],
) -> c.HttpClientService[HttpClientError]:
    def send(
        _request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.never

    return c.make(send)


def test_interrupting_a_request_aborts_its_signal() -> None:
    signals: list[AbortSignal] = []
    assert _run(_never_sending(signals).get("http://test/").timeout("10 millis").option()) is None
    assert signals[0].aborted


def test_interrupting_a_body_read_aborts_the_request() -> None:
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, fx.stream.never))

    reading = (
        c.make(send).get("http://test/").flat_map(lambda r: r.text.timeout("10 millis").option())
    )
    assert _run(reading) is None
    assert signals[0].aborted


def test_with_scope_owns_requests_another_client_sends_while_it_executes() -> None:
    """As Effect's ``withScope`` (#10363): ownership follows the execution, so a request a
    middleware sends with another client is attached to the scope too, unless that client's
    request runs in a scope of its own."""
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "body"))

    other = c.make(send)
    shared = c.make(send).tap(lambda _r: other.get("http://other/")).with_scope()
    _run(fx.scoped(shared.get("http://test/")))
    assert [signal.aborted for signal in signals] == [True, True]

    signals.clear()
    seen: list[list[bool]] = []
    own = other.with_scope()

    def helper(_response: res.HttpClientResponse) -> fx.Effect[None, HttpClientError]:
        helped = fx.scoped(own.get("http://other/"))
        return helped.and_then(fx.sync(lambda: seen.append([s.aborted for s in signals])))

    apart = c.make(send).tap(helper).with_scope()
    _run(fx.scoped(apart.get("http://test/")))
    assert seen == [[False, True]]
    assert [signal.aborted for signal in signals] == [True, True]


type _Wrap = Callable[[c.HttpClientService[HttpClientError, Any]], c.HttpClientService[Any, Any]]

_REWRITERS: dict[str, _Wrap] = {
    "map_request": lambda client: client.map_request(lambda r: r.set_header("x-rewritten", "1")),
    "with_cookies_ref": lambda client: client.with_cookies_ref(
        fx.run_blocking(fx.Ref.make((cookies.make_cookie_unsafe("a", "1"),)))
    ),
    "follow_redirects": lambda client: client.follow_redirects(),
    "retry_transient": lambda client: client.retry_transient(times=1),
}


@pytest.mark.parametrize("outside", [True, False], ids=["with_scope outside", "with_scope inside"])
@pytest.mark.parametrize("wrapper", list(_REWRITERS))
def test_with_scope_owns_every_request_the_transport_sends(wrapper: str, outside: bool) -> None:
    """Effect #10363: whichever wrapper rewrites or resends the request, and on whichever side
    of ``with_scope`` it sits, every request the transport saw stays open until the scope
    closes (but a redirect hop, which is discarded), and closing it aborts them all."""
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        if request.url.endswith("/start"):
            return fx.succeed(res.make(request, None, status=302, headers={"location": "/end"}))
        if len(signals) == 1 and wrapper == "retry_transient":
            return fx.succeed(res.make(request, None, status=503))
        return fx.succeed(res.make(request, "body"))

    wrap = _REWRITERS[wrapper]
    base = c.make(send)
    client = wrap(base).with_scope() if outside else wrap(base.with_scope())
    url = "http://test/start" if wrapper == "follow_redirects" else "http://test/"
    open_: list[list[bool]] = []
    kept: list[res.HttpClientResponse] = []

    def record(response: res.HttpClientResponse) -> None:
        kept.append(response)
        open_.append([signal.aborted for signal in signals])

    _run(fx.scoped(client.get(url).map(record)))
    # follow_redirects aborts the hop it discards at once, as Effect's does.
    expected = {"follow_redirects": [True, False], "retry_transient": [False, False]}
    assert open_ == [expected.get(wrapper, [False])]
    assert [signal.aborted for signal in signals] == [True] * len(open_[0])


def test_transient_statuses_are_effects_list_not_every_5xx() -> None:
    request = req.get("http://test/")
    transient = {s for s in range(100, 600) if c.is_transient_response(res.make(request, status=s))}
    assert transient == {408, 429, 500, 502, 503, 504}
