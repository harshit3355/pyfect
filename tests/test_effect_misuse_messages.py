"""Using an effect the way asyncio or a method chain would gives a message that says what to
write instead, in public names.

- `await eff` raises `TypeError` naming `run_async` and `yield from`.
- The combinators that remove something from a type are functions for `.pipe`, never methods
  (pyright binds `self` first and erases the wrong thing). `eff.catch_tag(...)` raises an
  `AttributeError` showing the `.pipe(fx.catch_tag(...))` form. pyright still reports the
  attribute as unknown (`tests/type_checks.py`).
"""

import asyncio
import inspect
import re
import traceback

import pytest

import pyfect as fx
from pyfect._effect_misuse import PIPE_ONLY


def test_awaiting_an_effect_says_to_use_run_async_or_yield_from():
    async def main() -> object:
        return await fx.succeed(1)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]

    with pytest.raises(TypeError) as raised:
        asyncio.run(main())
    message = str(raised.value)
    assert message.startswith("an Effect can't be awaited")
    assert "await fx.run_async(eff)" in message
    assert "yield from eff" in message
    assert "_Succeed" not in message


@pytest.mark.parametrize("name", sorted(PIPE_ONLY))
def test_a_pipe_only_combinator_used_as_a_method_shows_the_pipe_form(name: str):
    with pytest.raises(AttributeError) as raised:
        getattr(fx.fail("boom"), name)
    message = str(raised.value)
    assert message.startswith(f"Effect has no method {name}")
    assert f".pipe(fx.{name}" in message
    assert "_FailCause" not in message
    # Python's "Did you mean" would suggest a method that is not the fix.
    assert "Did you mean" not in "".join(traceback.format_exception(raised.value))
    assert not hasattr(fx.succeed(1), name)


def test_other_missing_attributes_keep_python_s_message():
    with pytest.raises(AttributeError, match="has no attribute 'no_such_method'"):
        fx.succeed(1).no_such_method  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]  # noqa: B018


def _pipe_only_in_docstrings() -> set[str]:
    """Public functions of `pyfect` that are not methods and whose docstring shows them
    used with `.pipe(`: the combinators a user might call as a method."""
    found: set[str] = set()
    for name in fx.__all__:
        value = getattr(fx, name)
        if not inspect.isfunction(value) or hasattr(fx.Effect, name):
            continue
        if re.search(rf"\.pipe\((?:fx\.)?{name}\b", value.__doc__ or ""):
            found.add(name)
    return found


def test_every_pipe_only_combinator_is_listed():
    # A new curried combinator documented with `.pipe(name(...))` gets the message too.
    assert _pipe_only_in_docstrings() <= PIPE_ONLY
    assert all(callable(getattr(fx, name)) for name in PIPE_ONLY)
