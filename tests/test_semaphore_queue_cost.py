"""A semaphore's queue costs time linear in its length, as in Effect 4.1.4+
(#10595): queueing, releasing and leaving do not scan every waiter when none
can fit in the free permits."""
# pyright: reportPrivateUsage=false

from collections.abc import Iterator
from typing import Any

import pyfect as fx


class _CountingWaiters(dict[Any, None]):
    """The semaphore's queue, counting the waiters its scans visit."""

    visits = 0

    def __iter__(self) -> Iterator[Any]:
        for waiter in super().__iter__():
            self.visits += 1
            yield waiter


def _visits_queueing(n: int, permits: int) -> int:
    """Queue ``n`` requests for ``permits`` each behind a semaphore of
    ``permits`` with all taken but one, release one permit, interrupt them."""

    @fx.gen
    def program():
        sem = yield from fx.Semaphore.make(permits)
        yield from sem.take(permits)
        waiters = _CountingWaiters()
        sem._waiters = waiters
        yield from sem.release(1)
        fibers = yield from fx.for_each(
            range(n), lambda _: sem.take(permits).fork(start_immediately=True)
        )
        yield from sem.release(0)
        yield from fx.yield_now()
        yield from fx.Fiber.interrupt_all(fibers)
        return waiters.visits

    return fx.run_blocking(program)


def test_queueing_requests_that_cannot_fit_visits_each_waiter_a_bounded_number_of_times():
    n = 2_000
    assert _visits_queueing(n, permits=2) < 4 * n
