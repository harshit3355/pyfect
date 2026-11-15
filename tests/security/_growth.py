"""How a parser's cost grows with its input, for inputs a peer chooses.

A parser that copies its buffer on every token, rescans what it already read, or appends to a
string attribute takes time quadratic in input a peer controls (CPython's in-place ``str +=``
only applies to a local variable; JavaScript's ropes, which Effect relies on, make the same
code linear there). ``growth`` measures a piece of work at a size and at ``FACTOR`` times it:
linear work grows ``FACTOR`` times, ``n log n`` a little more, quadratic work ``FACTOR**2``
times. ``BOUND`` sits between. Times are the thread's CPU time, the least of a few runs with
the collector off, so a loaded machine does not decide the outcome; the size first doubles
until the small run takes ``MIN_SECONDS``, so fixed costs do not hide the growth.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from dataclasses import dataclass

FACTOR = 8
BOUND = 24
"""Linear work grows 8 times, ``n log n`` about 10, ``n ** 1.5`` about 23, quadratic 64."""
MIN_SECONDS = 0.002
MAX_SIZE = 1 << 22
RUNS = 3

type Work = Callable[[], object]
type Make = Callable[[int], Work]
"""Given a size, the work of parsing an input of that size (built before the clock starts)."""


def cpu(work: Work, runs: int = RUNS) -> float:
    """The least thread CPU time of ``runs`` runs of ``work``."""
    best = float("inf")
    enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for _ in range(runs):
            start = time.thread_time()
            work()
            best = min(best, time.thread_time() - start)
    finally:
        if enabled:
            gc.enable()
    return best


@dataclass(frozen=True, slots=True)
class Growth:
    size: int
    small: float
    large: float

    @property
    def ratio(self) -> float:
        return self.large / max(self.small, 1e-6)

    @property
    def cheap(self) -> bool:
        """Both runs are too quick to measure: the input is refused or bounded early."""
        return self.large < MIN_SECONDS * FACTOR

    def __str__(self) -> str:
        return (
            f"size {self.size}: {self.small * 1000:.2f} ms, size {self.size * FACTOR}: "
            f"{self.large * 1000:.2f} ms, {self.ratio:.1f}x (linear is {FACTOR}x, "
            f"the bound {BOUND}x)"
        )


def growth(make: Make, size: int, max_size: int = MAX_SIZE) -> Growth:
    """``make``'s work at ``size`` (doubled until it takes ``MIN_SECONDS``) and at ``FACTOR``
    times that size."""
    while True:
        small = cpu(make(size))
        if small >= MIN_SECONDS or size * 2 * FACTOR > max_size:
            break
        size *= 2
    return Growth(size, small, cpu(make(size * FACTOR)))


def assert_near_linear(make: Make, size: int, max_size: int = MAX_SIZE) -> Growth:
    """Fails when ``make``'s work grows faster than ``BOUND`` over ``FACTOR`` times the size."""
    found = growth(make, size, max_size)
    if not found.cheap and found.ratio > BOUND:
        # One more measurement, so that a pause of the machine during one run does not decide.
        found = growth(make, found.size, max_size)
    assert found.cheap or found.ratio <= BOUND, f"superlinear: {found}"
    return found
