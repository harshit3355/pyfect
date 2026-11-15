"""How a piece of work grows with its input: for tests that pin peer input to
near-linear cost. The work is timed at two sizes ``factor`` apart, by the
thread's CPU time and the least of a few runs, so a loaded machine does not
decide it; linear work grows ``factor`` times, quadratic ``factor**2``."""

from __future__ import annotations

import time
from collections.abc import Callable

type Work = Callable[[], object]
type Sized = Callable[[int], Work]
"""Given a size, the work at that size (built before the timing starts)."""


def cpu(work: Work, runs: int = 3) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.thread_time()
        work()
        best = min(best, time.thread_time() - start)
    return best


def growth(sized: Sized, size: int, factor: int = 8) -> float:
    """CPU time at ``size * factor`` over CPU time at ``size``."""
    small, large = sized(size), sized(size * factor)
    return cpu(large) / max(cpu(small), 1e-4)


def assert_near_linear(sized: Sized, size: int, factor: int = 8) -> None:
    """Fails when the work grows by ``factor**2 / 2`` or more over a
    ``factor`` times larger input (linear grows ``factor``)."""
    ratio = growth(sized, size, factor)
    assert ratio < factor * factor / 2, f"{factor}x the input took {ratio:.1f}x the time"
