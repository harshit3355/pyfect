"""Running a channel again: ``repeat``, ``forever``, ``retry``, and pacing
items with ``schedule``.

Each run of the repeated channel builds its pull in a child of the
channel's scope, closed with the run's exit before the next run starts,
so resources do not pile up over repetitions.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from pyfect._core import Effect, _FailCause, _Gen, _Locally, _MatchCause, _Succeed, _Suspend
from pyfect.cause import Fail
from pyfect.cause import fail as fail_cause
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._constructors import suspend, unwrap_effect
from pyfect.channel._context import provide_service_effect
from pyfect.channel._lifecycle import on_first
from pyfect.exit import Exit, Failure
from pyfect.pull import catch_done, done_exit_from_cause
from pyfect.schedule import Schedule
from pyfect.schedule._drive import resolve_policy
from pyfect.schedule._model import (
    CurrentMetadata,
    Metadata,
    MetadataStep,
    to_step_with_metadata,
    to_step_with_sleep,
)
from pyfect.scope import CloseableScope, Scope

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type OnExit = Callable[[Exit[Any, Any], CloseableScope], Effect[Any, Any, Any]]
type Policy = Schedule[Any, Any, Any, Any] | Callable[[Any], Any]

_VOID: Effect[None] = _Succeed(None)


def repeat_loop(self: AnyChannel, on_exit: OnExit) -> Channel_:
    """Run ``self`` again each time ``on_exit(exit, scope)`` succeeds after
    a run; its failure (or end) is the channel's."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return _Succeed(_Suspend(_RepeatLoop(self, upstream, scope, on_exit).next_pull))

    return from_transform(transform)


class _RepeatLoop:
    """One run of ``repeat_loop``. It keeps the current run's pull bare and
    wraps it with its recovery (itself) on each pull: a stored wrapped pull
    would refer back here and keep the run alive after it ends."""

    __slots__ = ("channel", "current", "on_exit", "scope", "upstream")

    def __init__(
        self, channel: AnyChannel, upstream: AnyPull, scope: CloseableScope, on_exit: OnExit
    ) -> None:
        self.channel = channel
        self.upstream = upstream
        self.scope = scope
        self.on_exit = on_exit
        self.current: tuple[AnyPull, CloseableScope] | None = None

    def next_pull(self) -> AnyPull:
        current = self.current
        return self.make_pull() if current is None else _MatchCause(current[0], self, None)

    def make_pull(self) -> AnyPull:
        run_scope = self.scope.fork_unsafe()

        def started(pull: AnyPull) -> AnyPull:
            self.current = (pull, run_scope)
            return _MatchCause(pull, self, None)

        return self.channel._transform(self.upstream, run_scope).flat_map(started)

    def __call__(self, cause: Any) -> AnyPull:
        assert self.current is not None
        ex = done_exit_from_cause(cause)
        # As Effect's: ``on_exit`` and ``make_pull`` are called in the
        # continuations, not as effects of their own.
        return (
            self.current[1]
            .close(ex)
            .flat_map(lambda _: self.on_exit(ex, self.scope))
            .flat_map(lambda _: self.make_pull())
        )


def _with_metadata(self: AnyChannel, read: Callable[[], Metadata[Any, Any]]) -> AnyChannel:
    return provide_service_effect(CurrentMetadata, _Suspend(lambda: _Succeed(read())))(self)


def repeat(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def start(step: MetadataStep[Any, Any, Any, Any]) -> AnyChannel:
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def stepped(ex: Exit[Any, Any], _: CloseableScope) -> Effect[Any, Any, Any]:
            if isinstance(ex, Failure):
                return _FailCause(ex.cause)

            def keep(next_meta: Metadata[Any, Any]) -> None:
                nonlocal meta
                meta = next_meta

            return catch_done(step(ex.value).map(keep), lambda _: end_with(ex.value))

        return repeat_loop(_with_metadata(self, lambda: meta), stepped)

    return unwrap_effect(to_step_with_metadata(schedule).map(start))


def forever(self: AnyChannel) -> Channel_:
    def again(ex: Exit[Any, Any], _: CloseableScope) -> Effect[None, Any, Any]:
        return _FailCause(ex.cause) if isinstance(ex, Failure) else _VOID

    return repeat_loop(self, again)


def retry(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def build() -> Channel_:
        step: MetadataStep[Any, Any, Any, Any] | None = None
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def reset(_: Any) -> Effect[None]:
            nonlocal step
            step = None
            return _VOID

        def stepped(ex: Exit[Any, Any], scope: CloseableScope) -> Effect[Any, Any, Any]:
            if not isinstance(ex, Failure):
                return end_with(ex.value)
            found = ex.cause.find_recoverable_error()
            if not isinstance(found, Fail):
                return _FailCause(found)
            error = found.error

            # Effect's ``Effect.gen`` making the step once, then stepping.
            def body() -> Generator[Effect[Any, Any, Any], Any]:
                nonlocal step, meta
                made: MetadataStep[Any, Any, Any, Any] = (
                    (yield to_step_with_metadata(schedule)) if step is None else step
                )
                step = made
                meta = yield made(error)

            failed = _FailCause(fail_cause(error))
            stepping = catch_done(_Gen(body), lambda _: failed)
            return _Locally(stepping, lambda ctx: ctx.add(Scope, scope))

        with_reset = on_first(_with_metadata(self, lambda: meta), reset)
        return repeat_loop(with_reset, stepped)

    return suspend(build)


def schedule(self: AnyChannel, policy: Schedule[Any, Any, Any, Any]) -> Channel_:
    # Effect's: the pull, tapped with the step (which sleeps); the step's
    # ``Done`` ends the channel with the schedule's output.
    def with_step(pull: AnyPull, step: Callable[[Any], Effect[Any, Any, Any]]) -> AnyPull:
        return pull.tap(step)

    return transform_pull(
        self,
        lambda pull, _: to_step_with_sleep(policy).map(lambda step: with_step(pull, step)),
    )
