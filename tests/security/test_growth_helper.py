"""``assert_near_linear`` tells a one-time step in cost per unit (an input outgrowing a CPU
cache between the two sizes) from growth that is superlinear at every size."""

from __future__ import annotations

import gc

import pytest

from ._growth import MIN_SECONDS, Make, assert_near_linear, cpu


def _units_for(seconds: float) -> int:
    """About how many ``sum(range(n))`` units take ``seconds`` of CPU here."""
    probe = 1_000_000
    return max(1, int(probe * seconds / max(cpu(lambda: sum(range(probe))), 1e-6)))


def _base() -> int:
    return _units_for(MIN_SECONDS * 1.5)


def _no_doubling(size: int) -> int:
    # growth() doubles the size while it can; a cap one below twice FACTOR keeps it at ``size``.
    return size * 16 - 1


def test_a_cost_step_between_the_two_sizes_is_not_superlinear() -> None:
    base = _base()
    step_at = base * 2  # between the small size and the large one, as a cache size would be

    def make(n: int):
        units = n if n < step_at else 4 * n  # each unit costs 4 times more past the step
        return lambda: sum(range(units))

    assert_near_linear(make, base, _no_doubling(base))


def test_quadratic_work_still_fails() -> None:
    base = _base()
    make: Make = lambda n: lambda: sum(range(n * n // base))  # noqa: E731
    with pytest.raises(AssertionError, match="superlinear"):
        assert_near_linear(make, base, _no_doubling(base))


def test_linear_work_passes() -> None:
    base = _base()
    make: Make = lambda n: lambda: sum(range(n))  # noqa: E731
    assert_near_linear(make, base, _no_doubling(base))


def test_measuring_collects_only_the_young_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full collection walks the whole test process's heap: it was 90% of every parser case's
    time, and the collector is off while the work runs anyway."""
    generations: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: generations.append(generation) or 0)
    cpu(lambda: None)
    assert generations and max(generations) < 2
