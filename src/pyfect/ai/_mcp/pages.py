"""MCP list pages: every list fits on one page, as in Effect.

The server never issues a ``nextCursor``, so a request carrying a cursor (even ``""``) names
a page that does not exist and fails with ``InvalidParams("Unknown cursor")``.
"""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.ai.mcp_schema import InvalidParams
from pyfect.effect import fail, void


def reject_cursor(cursor: str | None) -> Effect[None, InvalidParams]:
    """Effect's ``McpProtocol.rejectCursor``."""
    return void if cursor is None else fail(InvalidParams("Unknown cursor"))
