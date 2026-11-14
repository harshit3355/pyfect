"""A request's progress goes out only while the request is live (Effect's ``RequestLiveness``).

A handler's progress can be held up on its way to the client: queued behind a write to a
client that stopped reading, or sent by a fiber that outlives the request. Effect drops it
once the request is over, and so does pyfect: a progress notification is a ``Progress``
carrying its request's ``Liveness``; none is sent once its request is answered, and the
stdio and RPC transports, which hold messages back for a slow client, ask ``dropped`` just
before writing one. Other notifications are always written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyfect.context import Tag


@dataclass(eq=False, slots=True)
class Liveness:
    """Where a request is in its life, as its progress sees it."""

    answered: bool = False
    """The request has its answer, or will get none: it sends no more progress."""
    abandoned: bool = False
    """Cancelled, or its client left: progress still queued for it is dropped too."""

    def abandon(self) -> None:
        self.answered = True
        self.abandoned = True


class RequestLiveness(Tag[Liveness], key="pyfect/ai/McpServer/RequestLiveness"):
    """The ``Liveness`` of the request a fiber serves (or was forked from)."""


class Progress(dict[str, Any]):
    """A progress notification, as written, of the request whose ``liveness`` it carries."""

    __slots__ = ("liveness",)

    def __init__(self, message: dict[str, Any], liveness: Liveness) -> None:
        super().__init__(message)
        self.liveness = liveness


def dropped(message: object) -> bool:
    """Whether a transport about to write ``message`` must drop it instead."""
    return isinstance(message, Progress) and message.liveness.abandoned
