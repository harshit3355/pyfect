"""A TaggedError raised in an effect body is a defect, as an exception thrown in Effect's
`gen` is, so `catch_tag` never sees it. What a run prints for such a defect says how to fail
with the error instead; the cause itself is not changed."""

import traceback
from dataclasses import dataclass

import pytest

import pyfect as fx

HINT = "NotFound was raised, so it is a defect, not a typed failure"


@dataclass
class NotFound(fx.TaggedError):
    key: str


@fx.fn
def raises(key: str):
    yield from fx.void
    raise NotFound(key)


def test_the_pretty_cause_of_a_raised_tagged_error_says_how_to_fail_with_it():
    exit = fx.run_blocking_exit(raises("a"))
    assert isinstance(exit, fx.Failure)
    # Only the rendering changes: the cause holds the defect as it was raised.
    assert exit.cause.defects == (NotFound("a"),)
    assert exit.cause.find_error() == fx.Err(exit.cause)
    rendered = exit.cause.pretty()
    assert HINT in rendered
    assert "return (yield from NotFound(...))" in rendered
    assert "fx.fail(error)" in rendered
    assert rendered.count(HINT) == 1


def test_run_blocking_raises_it_with_the_hint_as_a_note_once():
    for _ in range(2):
        with pytest.raises(NotFound) as raised:
            fx.run_blocking(raises("a"))
        printed = "".join(traceback.format_exception(raised.value))
        assert printed.count(HINT) == 1
        assert raised.value.__notes__ is not None
        exit = fx.run_blocking_exit(fx.die(raised.value))
        assert isinstance(exit, fx.Failure)
        assert exit.cause.pretty().count(HINT) == 1


def test_a_tagged_error_made_a_defect_without_being_raised_has_no_hint():
    exit = fx.run_blocking_exit(fx.fail(NotFound("a")).or_die())
    assert isinstance(exit, fx.Failure)
    assert "NotFound" in exit.cause.pretty()
    assert HINT not in exit.cause.pretty()


def test_a_failed_tagged_error_has_no_hint():
    exit = fx.run_blocking_exit(fx.fail(NotFound("a")))
    assert isinstance(exit, fx.Failure)
    assert HINT not in exit.cause.pretty()
