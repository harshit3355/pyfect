"""The services an entity handler can read."""

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.context import Tag
from pyfect.latch import Latch


class CurrentAddress(Tag[EntityAddress], key="effect/cluster/Entity/EntityAddress"):
    """The address of the entity handling the current request."""


class CurrentRunnerAddress(Tag[RunnerAddress], key="effect/cluster/Entity/RunnerAddress"):
    """The address of the runner the entity runs on."""


class KeepAliveLatch(Tag[Latch], key="effect/cluster/Entity/KeepAliveLatch"):
    """Closed while ``keep_alive(True)`` keeps the entity alive."""


class KeepAliveHandler(
    Tag[Callable[[bool], Effect[None]]], key="effect/cluster/Entity/KeepAliveHandler"
):
    """The runtime hook behind ``keep_alive``. A runtime that can pin an
    entity in memory provides it: the handler gets ``True`` while a holder
    keeps the entity alive and ``False`` once the last one lets go. When
    provided, ``keep_alive`` calls it instead of sending itself a message."""


__all__ = ["CurrentAddress", "CurrentRunnerAddress", "KeepAliveHandler", "KeepAliveLatch"]
