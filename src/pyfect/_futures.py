"""Completing an asyncio future from a callback.

A future handed to a callback (a fiber's exit observer, a
``call_soon_threadsafe``) can be cancelled before the callback runs, when
the task awaiting it is cancelled. ``set_result`` then raises
``InvalidStateError`` into whoever called the callback, which for an exit
observer stops the fiber's other observers. ``settle`` is the one way pyfect
completes such a future (``tests/test_future_callbacks.py``).
"""

from __future__ import annotations

import asyncio


def settle[A](future: asyncio.Future[A], value: A) -> None:
    """Set ``future``'s result, unless it is already done (cancelled)."""
    if not future.done():
        future.set_result(value)
