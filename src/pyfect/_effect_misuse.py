"""What ``Effect`` says when it is given a method it deliberately lacks. Runtime only:
pyright never sees ``__getattr__``, so it keeps reporting ``eff.catch_tag`` as an error
(``tests/type_checks.py``).

``Effect`` has no ``__await__``, not even one raising a clearer error: that would make
``inspect.isawaitable(eff)`` true, and libraries that await whatever is awaitable would
start raising on effects they pass through today (``tests/test_effect_misuse_messages.py``)."""

import functools
from collections.abc import Callable
from typing import Any, Final, NoReturn, cast

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


def install(cls: type) -> None:
    """Give ``cls`` (``Effect``) these attributes."""
    setattr(cls, "__getattr__", missing_attribute)  # noqa: B010


class _EffectMaker:
    """A function of no arguments that makes an effect, such as ``yield_now``, whose missing
    attributes say to call it: ``fx.yield_now.fork()`` is a mistake for
    ``fx.yield_now().fork()`` (Effect's ``yieldNow`` is a value)."""

    def __init__(self, make: Callable[[], object]) -> None:
        functools.update_wrapper(self, make)

    def __call__(self) -> object:
        return self.__wrapped__()

    def __repr__(self) -> str:
        return repr(self.__wrapped__)

    def __iter__(self) -> NoReturn:
        raise TypeError(
            f"{self.__name__} is a function that makes an effect, not an effect: "
            f"write `yield from fx.{self.__name__}()`"
        )

    def __getattr__(self, name: str) -> NoReturn:
        from pyfect._core import Effect

        if hasattr(Effect, name) or name in PIPE_ONLY:
            # No `obj`: Python would add a "Did you mean" for an attribute that is not it.
            raise AttributeError(
                f"{self.__name__} is a function that makes an effect, not an effect: "
                f"call it first, as in fx.{self.__name__}().{name}(...)",
                name=name,
            )
        raise AttributeError(f"'function' object has no attribute {name!r}", name=name, obj=self)

    __wrapped__: Callable[[], object]
    __name__: str


def effect_maker[F: Callable[[], Any]](make: F) -> F:
    """``make`` as it is for pyright; at run time, a missing attribute says to call it."""
    return cast("F", _EffectMaker(make))
