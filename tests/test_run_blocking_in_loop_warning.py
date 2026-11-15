"""`run_blocking` on a thread whose asyncio loop is running blocks that loop until the effect
is done: a coroutine or a Jupyter cell freezes. It still runs, as before, and warns with
`RunBlockingInEventLoopWarning` naming `run_async`. pytest turns the warning into an error
(pyproject.toml), so a test that does this on purpose says so."""

import asyncio
import warnings

import pytest

import pyfect as fx


@pytest.mark.parametrize("run", [fx.run_blocking, fx.run_blocking_exit], ids=lambda f: f.__name__)
def test_run_blocking_inside_a_running_loop_warns_naming_run_async(run: object):
    async def main() -> object:
        return run(fx.succeed(1))  # pyright: ignore[reportCallIssue, reportUnknownVariableType]

    with pytest.warns(fx.RunBlockingInEventLoopWarning) as caught:
        result = asyncio.run(main())
    assert result in (1, fx.Success(1))
    assert len(caught) == 1
    message = str(caught[0].message)
    assert "await fx.run_async(eff)" in message
    # The warning points at the caller's line, not at pyfect.
    assert caught[0].filename == __file__


def test_it_is_a_runtime_warning():
    assert issubclass(fx.RunBlockingInEventLoopWarning, RuntimeWarning)


def test_run_blocking_without_a_running_loop_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert fx.run_blocking(fx.succeed(1)) == 1

        async def main() -> int:
            return await fx.run_async(fx.succeed(2))

        assert asyncio.run(main()) == 2
