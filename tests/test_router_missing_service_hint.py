"""A route that reads a service nobody gave the request dies with ``MissingServiceError``,
as in Effect. When that happens while a request is handled, the error carries a note that
points to ``router.provide_request``: ``layer.provide`` on the routes layer is the natural
first try, and it gives the service only to the layer that registers the routes (Effect's
``Layer.provide`` on an ``HttpRouter.add`` layer does the same)."""

from typing import Any, Never, Protocol

import pyfect as fx
from pyfect import layer, testing
from pyfect.cause import Die
from pyfect.context import MissingServiceError
from pyfect.exit import Exit, Failure
from pyfect.http import router, server_response
from pyfect.http.client import HttpClient


class Greeter(Protocol):
    def greet(self) -> str: ...


class Greeting(fx.Tag[Greeter]): ...


class Hello:
    def greet(self) -> str:
        return "hello"


Stub = layer.succeed(Greeting, Hello())


@fx.gen
def _handler():
    greeter = yield from Greeting()
    return server_response.text(greeter.greet())


Routes = router.add("GET", "/", _handler)


@fx.gen
def _get():
    http = yield from HttpClient()
    return (yield from (yield from http.get("http://localhost/")).text)


def _defect(exit: Exit[Any, Any]) -> BaseException:
    assert isinstance(exit, Failure)
    [reason] = [r for r in exit.cause.reasons if isinstance(r, Die)]
    assert isinstance(reason.defect, BaseException)
    return reason.defect


def test_a_service_missing_in_a_request_points_to_provide_request():
    # The routes layer still requires Requires[Greeting]: layer.provide does not remove it,
    # so the client layer requires Greeting and pyright would flag running this.
    routes: layer.Layer[Never, Never, Any] = Routes.pipe(layer.provide(Stub))
    program = _get.pipe(fx.provide(router.layer_in_memory_client(routes)))
    error = _defect(fx.run_blocking_exit(program))
    assert isinstance(error, MissingServiceError)
    assert str(error) == f"Service not found: {Greeting.key}"
    [note] = error.__notes__
    assert "router.provide_request(" in note
    assert "layer.provide" in note


@testing.effect
def test_provide_request_gives_the_route_its_service():
    client = router.layer_in_memory_client(Routes.pipe(router.provide_request(Stub)))
    assert (yield from _get.pipe(fx.provide(client))) == "hello"


def test_a_service_missing_outside_a_request_has_no_note():
    exit = fx.run_blocking_exit(Greeting())  # pyright: ignore[reportArgumentType]
    error = _defect(exit)
    assert isinstance(error, MissingServiceError)
    assert not getattr(error, "__notes__", ())
