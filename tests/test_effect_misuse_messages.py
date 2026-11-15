"""Using an effect the way a method chain would gives a message that says what to write
instead, in public names.

- An effect is not awaitable (`inspect.isawaitable` is false), so libraries that await
  whatever is awaitable pass it through.
- The combinators that remove something from a type are functions for `.pipe`, never methods
  (pyright binds `self` first and erases the wrong thing). `eff.catch_tag(...)` raises an
  `AttributeError` showing the `.pipe(fx.catch_tag(...))` form. pyright still reports the
  attribute as unknown (`tests/type_checks.py`).
"""

import inspect
import re
import traceback

import pytest

import pyfect as fx
from pyfect._effect_misuse import PIPE_ONLY


def test_an_effect_is_not_awaitable():
    # An __await__, even one raising a clearer TypeError, would make libraries that await
    # anything awaitable (GraphQL resolvers, pytest-asyncio, callback frameworks) raise on
    # effects they pass through today.
    assert inspect.isawaitable(fx.succeed(1)) is False
    assert not hasattr(fx.Effect, "__await__")


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
