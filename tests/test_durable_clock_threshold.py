"""``durable_clock.InMemoryThreshold`` (Effect 4.1.4's
``DurableClock.InMemoryThreshold``): the threshold a ``sleep`` without one
reads, so an engine whose timers are always durable can provide zero."""

from __future__ import annotations

from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.workflow import Complete, durable_clock, workflow
from pyfect.workflow.workflow_engine import (
    Encoded,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowInstanceService,
    make_unsafe,
)


class _Empty(TypedDict):
    pass


_Workflow = workflow.make(
    "DurableClock/Threshold", payload=S.Struct(_Empty), idempotency_key=lambda _: "one"
)


def _engine_calls(sleep: fx.Effect[None, Any, Any]) -> list[str]:
    """The engine operations ``sleep`` makes: ``activityExecute`` for an
    in-memory sleep, ``scheduleClock`` for a durable one."""
    calls: list[str] = []

    def unexpected(*_: Any, **__: Any) -> fx.Effect[Any]:
        return fx.die(RuntimeError("unexpected engine operation"))

    def record(name: str, value: Any) -> Any:
        def call(*_: object, **__: object) -> fx.Effect[Any]:
            return fx.sync(lambda: (calls.append(name), value)[1])

        return call

    engine = make_unsafe(
        Encoded(
            register=unexpected,
            execute=unexpected,
            poll=unexpected,
            interrupt=unexpected,
            interrupt_unsafe=unexpected,
            resume=unexpected,
            deferred_done=unexpected,
            activity_execute=record("activityExecute", Complete(Exit.succeed(None))),
            schedule_clock=record("scheduleClock", None),
            deferred_result=record("deferredResult", Exit.succeed(None)),
        )
    )
    instance = WorkflowInstanceService.initial(_Workflow, "execution")
    testing.run_test(
        sleep.pipe(fx.provide_service(WorkflowEngine, engine))
        .pipe(fx.provide_service(WorkflowInstance, instance))
        .or_die()
    )
    return calls


@pytest.mark.parametrize(
    ("duration", "expected"),
    [("60 seconds", "activityExecute"), ("61 seconds", "scheduleClock")],
)
def test_a_sleep_without_a_threshold_reads_the_default_of_60_seconds(
    duration: str, expected: str
) -> None:
    calls = _engine_calls(durable_clock.sleep(name="wait", duration=duration))
    assert calls[0] == expected


def test_a_provided_zero_threshold_makes_every_sleep_durable() -> None:
    sleep = durable_clock.sleep(name="wait", duration="10 millis").pipe(
        fx.provide_service(durable_clock.InMemoryThreshold, fx.duration.zero)
    )
    assert _engine_calls(sleep) == ["scheduleClock", "deferredResult"]


def test_an_explicit_threshold_wins_over_the_provided_one() -> None:
    sleep = durable_clock.sleep(
        name="wait", duration="10 millis", in_memory_threshold="1 second"
    ).pipe(fx.provide_service(durable_clock.InMemoryThreshold, fx.duration.zero))
    assert _engine_calls(sleep) == ["activityExecute"]
