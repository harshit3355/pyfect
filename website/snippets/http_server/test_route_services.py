from typing import Protocol

import pyfect as fx
from pyfect import layer, testing
from pyfect.http import router, server_response
from pyfect.http.client import HttpClient


class Checker(Protocol):
    def status(self, url: str) -> fx.Effect[int]: ...


class UrlChecker(fx.Tag[Checker]): ...


@fx.fn
def check():
    checker = yield from UrlChecker()
    status = yield from checker.status("https://example.com")
    return server_response.text(str(status))


# Requires[UrlChecker]: the route reads the service for each request.
Routes = router.add("GET", "/check", check())


class AlwaysOk:
    def status(self, url: str) -> fx.Effect[int]:
        return fx.succeed(200)


Stub = layer.succeed(UrlChecker, AlwaysOk())


@fx.gen
def get_check():
    res = yield from (yield from HttpClient()).get("http://localhost/check")
    return (yield from res.text)


@testing.effect
def test_check_with_a_stub_checker():
    client = router.layer_in_memory_client(Routes.pipe(router.provide_request(Stub)))
    assert (yield from get_check.pipe(fx.provide(client))) == "200"
