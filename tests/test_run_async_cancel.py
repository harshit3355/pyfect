"""Cancelling a task awaiting ``run_async`` interrupts the fiber and waits for
its finalizers, however often it is cancelled (Effect's ``runPromiseExit``
with its signal aborted twice settles after the finalizer)."""

import asyncio
import contextlib
import inspect
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

import pyfect as fx
import pyfect.schema as S
from pyfect import layer
from pyfect.option import Option
from pyfect.schema import getter as G
from pyfect.schema import transformation as T

type Entry = Callable[[fx.Effect[None]], Coroutine[Any, Any, Any]]


async def _cancel_twice_while_finalizing(run: Entry) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: errors.append(type(context.get("exception")).__name__)
    )
    log: list[str] = []
    finalizing = asyncio.Event()

    @fx.gen
    def finalizer():
        finalizing.set()
        yield from fx.sleep("50 millis")
        log.append("fin")

    task = asyncio.create_task(run(fx.never.ensuring(finalizer)))
    await asyncio.sleep(0.01)
    task.cancel()
    await finalizing.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    observed = list(log)
    await asyncio.sleep(0.1)
    return observed, errors


@pytest.mark.parametrize("entry", ["fx", "fx_exit", "runtime", "runtime_exit"])
def test_a_second_cancel_still_waits_for_the_finalizers(entry: str) -> None:
    async def main() -> tuple[list[str], list[str]]:
        async with fx.ManagedRuntime.make(layer.empty) as runtime:
            run: Entry = {
                "fx": fx.run_async,
                "fx_exit": fx.run_async_exit,
                "runtime": runtime.run_async,
                "runtime_exit": runtime.run_async_exit,
            }[entry]
            return await _cancel_twice_while_finalizing(run)

    assert asyncio.run(main()) == (["fin"], [])


def test_a_second_cancel_leaves_other_exit_observers_running() -> None:
    async def main() -> fx.Exit[Any, Any]:
        fibers: list[fx.Fiber[Any, Any]] = []

        def record() -> None:
            fiber = fx.Fiber.get_current()
            assert fiber is not None
            fibers.append(fiber)

        eff = fx.sync(record).and_then(fx.never).ensuring(fx.sleep("50 millis"))
        task = asyncio.create_task(fx.run_async(eff))
        await asyncio.sleep(0.01)
        waiter = asyncio.create_task(fx.run_async(fibers[0].await_exit()))
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        async with asyncio.timeout(2):
            return await waiter

    ex = asyncio.run(main())
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def test_the_cancelled_await_still_raises_cancelled_error() -> None:
    async def main() -> None:
        task = asyncio.create_task(fx.run_async(fx.never.ensuring(fx.sleep("20 millis"))))
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())


def test_cancelling_an_awaited_standard_schema_validation_reports_no_loop_error() -> None:
    def later(os: Option[str], _: object) -> Any:
        return fx.sleep("20 millis").as_(os)

    schema = S.String.pipe(
        S.decode(T.Transformation(G.transform_optional_effect(later), G.passthrough()))
    )
    validate = getattr(S.to_standard_schema_v1(schema), "~standard").validate

    async def main() -> list[str]:
        errors: list[str] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: errors.append(type(context.get("exception")).__name__)
        )
        pending = validate("a")
        assert inspect.isawaitable(pending)

        async def wait() -> object:
            return await pending

        task = asyncio.create_task(wait())
        await asyncio.sleep(0.005)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        return errors

    assert asyncio.run(main()) == []
