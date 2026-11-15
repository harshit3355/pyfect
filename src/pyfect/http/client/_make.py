"""Building a client from a send function: URL building, tracing,
interruption (Effect's ``HttpClient.make``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pyfect._core import Effect, _WithFiber
from pyfect._effect_resources import _call_user
from pyfect._fiber import Fiber
from pyfect._js import to_well_formed
from pyfect._primitives import uninterruptible_mask
from pyfect.cause import Cause, Fail
from pyfect.cause import fail as fail_cause
from pyfect.clock import Clock
from pyfect.context import Reference
from pyfect.effect import fail, provide_service, succeed, sync
from pyfect.effect import fail_cause as fail_with_cause
from pyfect.exit import Failure
from pyfect.http import headers as _headers
from pyfect.http import trace_context
from pyfect.http import url as _url
from pyfect.http import url_params as _url_params
from pyfect.http.abort import AbortController, AbortSignal
from pyfect.http.client._service import HttpClientService
from pyfect.http.error import HttpClientError, InvalidUrlError, StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse, _InterruptibleResponse
from pyfect.result import Err, Ok
from pyfect.scope import CloseableScope, Scope
from pyfect.tracer import DisablePropagation, Span, TracerEnabled, TracerTimingEnabled
from pyfect.tracer._spans import in_parent_span, use_span

type Phase = Literal["request", "response"]
type Send = Callable[
    [HttpClientRequest, _url.Url, AbortSignal, Fiber[Any, Any]],
    Effect[HttpClientResponse, HttpClientError],
]
"""What a client backend implements: send the request to the URL (built
from its ``url``, ``url_params`` and ``hash``), stopping when the signal
aborts."""


class TracerDisabledWhen(Reference[Callable[[HttpClientRequest], bool]]):
    """Requests sent without a span (and without trace headers)."""

    @classmethod
    def default(cls) -> Callable[[HttpClientRequest], bool]:
        return lambda _request: False


class TracerHeaderFilter(Reference[Callable[[str, Phase], bool]]):
    """The headers recorded as span attributes (``http.request.header.x``),
    by name and phase. None by default."""

    @classmethod
    def default(cls) -> Callable[[str, Phase], bool]:
        return lambda _name, _phase: False


class TracerPropagationEnabled(Reference[bool]):
    """Whether requests carry ``traceparent`` and ``b3`` headers."""

    @classmethod
    def default(cls) -> bool:
        return True


class SpanNameGenerator(Reference[Callable[[HttpClientRequest], str]]):
    """The name of a request's span; its method by default."""

    @classmethod
    def default(cls) -> Callable[[HttpClientRequest], str]:
        return lambda request: request.method


class RequestScope(Reference[CloseableScope | None]):
    """The scope of the enclosing ``with_scope``, which owns every request the transport sends
    while that client executes (Effect's ``HttpClient`` ``RequestScope``)."""

    @classmethod
    def default(cls) -> CloseableScope | None:
        return None


def scoped[A, E, R](sending: Effect[A, E, R]) -> Effect[A, E, R | Scope]:
    """Run ``sending`` with the current ``Scope`` owning every request it sends."""
    return Scope().flat_map(lambda scope: sending.pipe(provide_service(RequestScope, scope)))


_DEFAULT_PORTS = {"http:": 80, "https:": 443, "ws:": 80, "wss:": 443}


def _add_url_attributes(span: Span, url: _url.Url, redacted: Sequence[_headers.Pattern]) -> None:
    query = _url_params.redact_url(url.search, redacted)[1:]
    span.attribute("url.full", _url_params.redact_url(url.href, redacted))
    span.attribute("url.path", url.pathname)
    if query:
        span.attribute("url.query", query)
    span.attribute("url.scheme", url.protocol[:-1])
    hostname = url.hostname
    if hostname:
        # URL keeps IPv6 brackets in the hostname; the semantic conventions do not.
        span.attribute("server.address", hostname[1:-1] if hostname[0] == "[" else hostname)
        port = int(url.port) if url.port else _DEFAULT_PORTS.get(url.protocol)
        if port is not None:
            span.attribute("server.port", port)


def _redacted_names(
    params: _url_params.UrlParams, names: Sequence[_headers.Pattern]
) -> Sequence[_headers.Pattern]:
    keys = [to_well_formed(key) for key, value in params if not isinstance(value, str)]
    return names if not keys else (*names, *keys)


def _add_header_attributes(
    span: Span,
    phase: Phase,
    headers: _headers.Headers,
    accept: Callable[[str, Phase], bool],
    redacted: Sequence[_headers.Pattern],
) -> None:
    for name, value in headers.items():
        if accept(name, phase):
            shown = "<redacted>" if _headers.is_redacted_name(name, redacted) else value
            span.attribute(f"http.{phase}.header.{name}", shown)


def _track(
    response: HttpClientResponse,
    controller: AbortController,
    scoped: bool,
    redacted_names: Sequence[_headers.Pattern],
) -> HttpClientResponse:
    # Body readers make errors with the runner's response while callers hold the wrapper, so
    # both carry the executing fiber's names.
    response._add_redacted_names(redacted_names)
    tracked = response if scoped else _interruptible(response, controller)
    if tracked is not response:
        tracked._add_redacted_names(redacted_names)
    # On the response, not in a table keyed by it: the controller reaches the response
    # again (through the request's span), which would keep such an entry forever.
    tracked._abort_with(controller.abort)
    return tracked


def _interruptible(response: HttpClientResponse, controller: AbortController) -> HttpClientResponse:
    """Abort when the unread ``response`` is collected, when a body read is
    interrupted, or when its stream ends."""
    finalizer = weakref.finalize(response, controller.abort)

    def release() -> None:
        finalizer.detach()

    return _InterruptibleResponse(response, controller.abort, release)


def _exchange(
    send: Send,
    request: HttpClientRequest,
    url: _url.Url,
    fiber: Fiber[Any, Any],
    on_response: Callable[[HttpClientResponse], None],
) -> Effect[HttpClientResponse, HttpClientError]:
    """Send ``request`` on a controller of its own, aborted when the request is interrupted
    before its response, and owned by the enclosing ``with_scope``'s scope if any."""
    scope = fiber.get_ref(RequestScope)
    controller = AbortController()
    redacted_names = fiber.get_ref(_url_params.CurrentRedactedNames)
    sending = _call_user(send, request, url, controller.signal, fiber)
    if scope is not None:
        # Registered before dispatch, so a scope already closed aborts the signal before the
        # transport sees it.
        sending = scope.add_finalizer(lambda _exit: sync(controller.abort)).and_then(sending)

    def on_failure(cause: Cause[HttpClientError]) -> Effect[HttpClientResponse, HttpClientError]:
        if cause.has_interrupts:
            controller.abort()
        # A transport callback outside this fiber may have made the error without its names.
        for reason in cause.reasons:
            if isinstance(reason, Fail):
                reason.error.reason._add_redacted_names(redacted_names)
        return fail_with_cause(cause)

    def on_success(response: HttpClientResponse) -> Effect[HttpClientResponse, HttpClientError]:
        tracked = _track(response, controller, scope is not None, redacted_names)
        on_response(tracked)
        return succeed(tracked)

    return uninterruptible_mask(
        lambda restore: restore(sending).match_cause_effect(
            on_failure=on_failure, on_success=on_success
        )
    )


def _send(
    send: Send, request: HttpClientRequest, fiber: Fiber[Any, Any]
) -> Effect[HttpClientResponse, HttpClientError]:
    match _url.make(request.url, request.url_params, request.hash):
        case Err(error):
            return fail(HttpClientError(InvalidUrlError(request, error)))
        case Ok(url):
            pass
    if (
        not fiber.get_ref(TracerEnabled)
        or fiber.get_ref(DisablePropagation)
        or fiber.get_ref(TracerDisabledWhen)(request)
    ):
        return _exchange(send, request, url, fiber, lambda _response: None)

    def traced(span: Span) -> Effect[HttpClientResponse, HttpClientError]:
        span.attribute("http.request.method", request.method)
        redacted_headers = fiber.get_ref(_headers.CurrentRedactedNames)
        _add_url_attributes(
            span,
            url,
            _redacted_names(request.url_params, fiber.get_ref(_url_params.CurrentRedactedNames)),
        )
        accept = fiber.get_ref(TracerHeaderFilter)
        _add_header_attributes(span, "request", request.headers, accept, redacted_headers)
        sent = (
            request.set_headers(trace_context.to_headers(span))
            if fiber.get_ref(TracerPropagationEnabled)
            else request
        )

        def on_response(response: HttpClientResponse) -> None:
            span.attribute("http.response.status_code", response.status)
            _add_header_attributes(span, "response", response.headers, accept, redacted_headers)
            if 400 <= response.status < 600:
                span.attribute("error.type", str(response.status))
                now = (
                    fiber.get_ref(Clock).now_nanos_unsafe()
                    if fiber.get_ref(TracerTimingEnabled)
                    else 0
                )
                error = HttpClientError(StatusCodeError(sent, response))
                span.end(now, Failure(fail_cause(error)))

        return in_parent_span(_exchange(send, sent, url, fiber, on_response), span)

    return use_span(fiber.get_ref(SpanNameGenerator)(request), traced, kind="client")


def make(send: Send) -> HttpClientService[HttpClientError]:
    """A client sending each request with ``send``. It builds the URL
    (failing with an ``InvalidUrlError``), runs each request in a client
    span with HTTP attributes and trace headers, and aborts the request's
    signal when it is interrupted or its unread response is dropped."""

    def postprocess(
        requests: Effect[HttpClientRequest, Any, Any],
    ) -> Effect[HttpClientResponse, HttpClientError]:
        return requests.flat_map(
            lambda request: _WithFiber(lambda fiber: _send(send, request, fiber))
        )

    return HttpClientService(postprocess, succeed)
