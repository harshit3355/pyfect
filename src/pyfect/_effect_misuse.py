"""What ``Effect`` says when it is used as an asyncio awaitable or given a method it
deliberately lacks. Runtime only: pyright never sees these attributes, so it keeps
reporting ``await eff`` and ``eff.catch_tag`` as errors (``tests/type_checks.py``)."""

from typing import Any, Final, NoReturn

PIPE_ONLY: Final = frozenset(
    {
        "catch_no_such_element",
        "catch_reason",
        "catch_reasons",
        "catch_tag",
        "provide",
        "provide_context",
        "provide_service",
        "provide_service_effect",
        "update_context",
        "with_execution_plan",
    }
)
"""The combinators that change an effect's error or service type, so they are functions
for ``.pipe`` and never methods: pyright binds ``self`` first and would remove the wrong
thing (``research/typing/exp3``)."""

# Used bare, not called with arguments first.
_BARE: Final = frozenset({"catch_no_such_element"})


def _pipe_form(name: str) -> str:
    usage = f"fx.{name}" if name in _BARE else f"fx.{name}(...)"
    return (
        f"Effect has no method {name}: it changes the effect's type, which pyright "
        f"checks only for a function given to .pipe. Write eff.pipe({usage})"
    )


def missing_attribute(self: object, name: str) -> NoReturn:
    """``Effect.__getattr__``, which Python calls only once normal lookup has failed."""
    if name in PIPE_ONLY:
        # No `obj`: Python would add a "Did you mean" for a method that is not it.
        raise AttributeError(_pipe_form(name), name=name)
    # The primitives are private classes; name the public one.
    kind = type(self).__name__
    raise AttributeError(
        f"{'Effect' if kind.startswith('_') else kind!r} object has no attribute {name!r}",
        name=name,
        obj=self,
    )


def awaited(_: Any) -> NoReturn:
    """``Effect.__await__``."""
    raise TypeError(
        "an Effect can't be awaited: it is a description of work, not a coroutine. "
        "In a coroutine, run it with `await fx.run_async(eff)`; in an effect generator, "
        "use `yield from eff`"
    )


def install(cls: type) -> None:
    """Give ``cls`` (``Effect``) these attributes."""
    setattr(cls, "__getattr__", missing_attribute)  # noqa: B010
    setattr(cls, "__await__", awaited)  # noqa: B010
