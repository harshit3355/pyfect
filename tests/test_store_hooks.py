"""Hooks Effect 4.1.4 exported for runtimes and stores outside its modules
(#7322): ``entity.KeepAliveHandler`` and ``persisted_queue.is_dead_letter_cause``."""

from __future__ import annotations

from typing import Any, Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import entity
from pyfect.persistence import persisted_queue as pq


def test_keep_alive_calls_a_provided_handler_instead_of_messaging_the_entity() -> None:
    calls: list[bool] = []

    def handler(enabled: bool) -> fx.Effect[None]:
        return fx.sync(lambda: calls.append(enabled))

    # The handler path reads neither Sharding nor the address.
    program = cast(
        "fx.Effect[None]",
        entity.keep_alive(True)
        .and_then(entity.keep_alive(False))
        .pipe(fx.provide_service(entity.KeepAliveHandler, handler)),
    )
    testing.run_test(program)
    assert calls == [True, False]


def test_is_dead_letter_cause_marks_a_payload_that_fails_to_decode() -> None:
    seen: list[tuple[Any, bool]] = []

    def body():
        memory = yield from pq.PersistedQueueStore()

        def take(
            options: pq.TakeOptions,
        ) -> fx.Effect[pq.TakenElement, pq.PersistedQueueError, fx.Scope]:
            def record(taken: pq.TakenElement) -> fx.Effect[None, Never, fx.Scope]:
                return fx.add_finalizer(
                    lambda exit_: fx.sync(
                        lambda: seen.append(
                            (
                                taken.element,
                                isinstance(exit_, fx.Failure)
                                and pq.is_dead_letter_cause(exit_.cause),
                            )
                        )
                    )
                )

            return memory.take(options).tap(record)

        store = pq.PersistedQueueStoreService(offer=memory.offer, take=take, cleanup=memory.cleanup)

        def run():
            yield from store.offer(name="hooks", id="poison", element="x", is_custom_id=True)
            yield from store.offer(name="hooks", id="ok", element=1, is_custom_id=True)
            queue = yield from pq.make(name="hooks", schema=S.Int, max_attempts=1)
            assert (yield from queue.take(lambda value, _: fx.succeed(value))) == 1
            yield from store.offer(name="hooks", id="bad", element=2, is_custom_id=True)
            assert (yield from queue.take(lambda _, __: fx.fail("boom")).flip()) == "boom"

        yield from fx.gen(run).pipe(
            fx.provide(
                pq.layer.pipe(fx.layer.provide(fx.layer.succeed(pq.PersistedQueueStore, store)))
            )
        )

    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(pq.layer_store_memory)).or_die())
    assert seen == [("x", True), (1, False), (2, False)]
