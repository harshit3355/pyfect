"""``help(fx.run_blocking)`` shows the implementation's signature, not the overloads, so it
used to read ``run_blocking(eff: Effect[Any, Never, Any], ...) -> Any``. The run functions'
implementations are generic in the success value (and the error, for the ``_exit`` forms),
so help shows that the result is the effect's value."""

import inspect
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx

RUNS: dict[str, tuple[Callable[..., Any], str, str]] = {
    "run_sync": (fx.run_sync, "Effect[A, Never, Any]", "A"),
    "run_blocking": (fx.run_blocking, "Effect[A, Never, Any]", "A"),
    "run_async": (fx.run_async, "Effect[A, Never, Any]", "A"),
    "run_sync_exit": (fx.run_sync_exit, "Effect[A, E, Any]", "Exit[A, E]"),
    "run_blocking_exit": (fx.run_blocking_exit, "Effect[A, E, Any]", "Exit[A, E]"),
    "run_async_exit": (fx.run_async_exit, "Effect[A, E, Any]", "Exit[A, E]"),
}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_help_shows_the_result_is_the_effect_s_value(name: str) -> None:
    function, effect, result = RUNS[name]
    signature = inspect.signature(function)
    assert signature.parameters["eff"].annotation == effect
    assert signature.return_annotation == result
