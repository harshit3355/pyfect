"""A request with a malformed JSON body gets a 400, and the server logs the failure at INFO as
Effect's ``HttpMiddleware.logger`` does (``Effect.log(cause)``). The JSON error is the client's
mistake, so it is logged as its message alone: its Python traceback runs through the ``json``
module and said nothing about the server, and made each bad request about 30 log lines."""

import asyncio
from typing import Any

import pyfect as fx
from pyfect import logger
from pyfect.cause import Cause
from pyfect.http import server_response
from pyfect.http.middleware import logger as http_logger
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import to_web_handler
from pyfect.logger import Logger, LogLevel
from pyfect.result import Ok


@fx.gen
def _app():
    request = yield from HttpServerRequest()
    yield from request.json
    return server_response.text("ok")


def test_a_malformed_json_body_is_logged_without_a_traceback() -> None:
    logs: list[tuple[Cause[Any], LogLevel]] = []
    recorder = Logger.make(lambda options: logs.append((options.cause, options.log_level)))

    async def main() -> int:
        handler = to_web_handler(
            _app, lambda inner: http_logger(inner).pipe(fx.provide(logger.layer([recorder])))
        )
        response = await handler(WebRequest("http://localhost/check", method="POST", body="{x"))
        return response.status

    assert asyncio.run(main()) == 400
    [(cause, level)] = logs
    assert level == LogLevel.INFO
    found = cause.find_error()
    assert isinstance(found, Ok)
    error = found.value
    assert isinstance(error, HttpServerError)
    assert isinstance(error.reason, RequestParseError)
    assert type(error.cause).__name__ == "JSONDecodeError"
    text = cause.pretty()
    assert "Traceback" not in text
    assert "RequestParseError (POST /check)" in text
    assert "JSONDecodeError: Expecting property name enclosed in double quotes" in text
