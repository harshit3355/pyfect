"""Whether work on peer input grows linearly: the thread's CPU time for an
input ``factor`` times longer, against the shorter one's. Linear work grows
``factor`` times and quadratic ``factor**2``; the check allows ``2 * factor``.
The least of a few runs, in CPU time, so a loaded machine does not decide it."""

from __future__ import annotations

import time
from collections.abc import Callable

_RUNS = 3


def _cpu(work: Callable[[], object]) -> float:
    best = float("inf")
    for _ in range(_RUNS):
        start = time.thread_time()
        work()
        best = min(best, time.thread_time() - start)
    return best


def growth(make: Callable[[int], Callable[[], object]], size: int, factor: int = 8) -> float:
    """How many times longer ``make(factor * size)``'s work takes than ``make(size)``'s."""
    small = _cpu(make(size))
    large = _cpu(make(factor * size))
    return large / max(small, 1e-6)


def is_linear(make: Callable[[int], Callable[[], object]], size: int, factor: int = 8) -> bool:
    """Linear on one of three tries: quadratic work fails every one."""
    return any(growth(make, size, factor) < 2 * factor for _ in range(3))
