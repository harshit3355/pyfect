"""A store a server's storage cannot open, and the protocol error a client
gets for it, so handlers never hide the reason behind a generic message."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pyfect.cause import Cause
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_message import EventLogProtocolError


class StoreUnavailable(ABC):
    """Mixed into a defect a storage raises when a store does not open for a
    reason its client should know, until the server's operator acts."""

    @property
    @abstractmethod
    def client_message(self) -> str:
        """What the client is told: nothing about other identities."""


def protocol_error(
    request_tag: str, public_key: str, store_id: StoreId, message: str
) -> Callable[[Cause[Any]], EventLogProtocolError]:
    """What a client is told when a storage call fails with ``cause``: an
    ``InternalServerError`` with ``message``, or with the client message of
    a ``StoreUnavailable`` defect (Effect's protocol has no other code for
    it). Handlers map every storage failure through this, never dropping
    the cause unread."""

    def convert(cause: Cause[Any]) -> EventLogProtocolError:
        unavailable = next((d for d in cause.defects if isinstance(d, StoreUnavailable)), None)
        if unavailable is None:
            return EventLogProtocolError(
                request_tag=request_tag,
                code="InternalServerError",
                message=message,
                public_key=public_key,
            )
        return EventLogProtocolError(
            request_tag=request_tag,
            code="InternalServerError",
            message=unavailable.client_message,
            public_key=public_key,
            store_id=store_id,
        )

    return convert
