"""Anthropic's server tools, in one place for the decoders (generated and streamed) and the
replay (``_prompt.py``): a block the decoders read is a block the replay can write back.

``server_tool_use`` names map to the provider tool they are calls of, and each provider tool to
the block its result arrives in. Code execution results all decode to the ``code_execution``
tool, so their block is read off the result's own ``type``.
"""

from __future__ import annotations

from typing import Literal, get_args

type ServerResultBlock = Literal[
    "mcp_tool_result",
    "code_execution_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
    "tool_search_tool_result",
    "web_fetch_tool_result",
    "web_search_tool_result",
]
SERVER_RESULT_BLOCKS: tuple[ServerResultBlock, ...] = get_args(ServerResultBlock.__value__)

SERVER_CALLS: dict[str, str] = {
    "code_execution": "code_execution",
    "bash_code_execution": "code_execution",
    "text_editor_code_execution": "code_execution",
    "web_fetch": "web_fetch",
    "web_search": "web_search",
    "tool_search_tool_bm25": "tool_search_tool_bm25",
    "tool_search_tool_regex": "tool_search_tool_regex",
}
"""A ``server_tool_use`` name to the provider tool it calls: code execution 20250825 runs
``bash_code_execution`` and ``text_editor_code_execution`` calls."""

RESULT_BLOCKS: dict[str, ServerResultBlock] = {
    "web_fetch": "web_fetch_tool_result",
    "web_search": "web_search_tool_result",
    "tool_search_tool_regex": "tool_search_tool_result",
    "tool_search_tool_bm25": "tool_search_tool_result",
}
"""The result block of each provider tool but code execution (``code_execution_block``) and
MCP (replayed by call id)."""

_CODE_EXECUTION_BLOCKS: tuple[tuple[str, ServerResultBlock], ...] = (
    ("bash_code_execution_", "bash_code_execution_tool_result"),
    ("text_editor_code_execution_", "text_editor_code_execution_tool_result"),
)


def code_execution_block(result_type: str) -> ServerResultBlock:
    """The block a code execution result of ``result_type`` arrives in: Anthropic prefixes
    the bash and text editor results (``bash_code_execution_result``,
    ``text_editor_code_execution_view_result``, their ``..._tool_result_error``) with their
    sub-tool, and the rest (``code_execution_result``, ``encrypted_code_execution_result``,
    ``code_execution_tool_result_error``) are code execution's own."""
    for prefix, block in _CODE_EXECUTION_BLOCKS:
        if result_type.startswith(prefix):
            return block
    return "code_execution_tool_result"


def is_code_execution_failure(result_type: str) -> bool:
    """Only the ``..._tool_result_error`` results are failures; a nonzero return code is a
    result."""
    return result_type.endswith("_tool_result_error")


def code_execution_blocks() -> frozenset[ServerResultBlock]:
    return frozenset({"code_execution_tool_result", *(b for _, b in _CODE_EXECUTION_BLOCKS)})
