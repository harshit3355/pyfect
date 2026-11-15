"""How much work a call does, for tests that bound it: linear, not quadratic, or cheap.

Count the work when you can (visits, comparisons, steps through a hook, as
``test_semaphore_queue_cost`` and ``test_equal_depth`` do). Measure it here when the
work that could blow up runs in C, where nothing counts it: ``re`` backtracking,
``str.find`` over a growing buffer, a buffer copied on every append.

The measure is this thread's CPU time (``time.thread_time``), with the collector off.
Waiting for the CPU, and work on other threads and processes, do not count, so a
loaded machine does not decide the check. What is left is noise in the speed of the
CPU itself (a slower core, a cold cache), which ``grows_linearly`` evens out by
measuring both sizes in turn and keeping each one's least time. Never compare
wall-clock time (``perf_counter``, ``monotonic``) in a growth check:
``tests/test_growth_checks.py`` fails one that does.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

type Work = Callable[[], object]
type Sized = Callable[[int], Work]
"""Given a size, the work of that much input (built before it is measured)."""

ROUNDS = 3


def cpu_seconds(work: Work) -> float:
    """This thread's CPU time for ``work``."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        start = time.thread_time()
        work()
        return time.thread_time() - start
    finally:
        if enabled:
            gc.enable()


def growth(sized: Sized, n: int, factor: int) -> tuple[float, float]:
    """The least CPU time of ``sized(n)`` and of ``sized(factor * n)``, measured in turn
    ``ROUNDS`` times."""
    small_work, large_work = sized(n), sized(factor * n)
    small = large = float("inf")
    for _ in range(ROUNDS):
        small = min(small, cpu_seconds(small_work))
        large = min(large, cpu_seconds(large_work))
    return small, large


def grows_linearly(sized: Sized, n: int, *, factor: int, limit: float, floor: float = 0.0) -> bool:
    """``factor`` times the input costs under ``limit`` times the work (linear work costs
    ``factor`` times, quadratic ``factor ** 2``), or the larger input costs under
    ``floor`` seconds either way."""
    small, large = growth(sized, n, factor)
    return large < floor or large < limit * small
