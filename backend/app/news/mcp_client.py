"""One helper to call a single tool on a hosted streamable-HTTP MCP server and return its text.

Sync wrapper: the explorer fetch path is a sync FastAPI route (runs in Starlette's threadpool,
so no event loop is running in this thread) -> asyncio.run is safe. `mcp` is imported lazily so
modules that monkeypatch this helper in tests don't require the SDK at import time."""
from __future__ import annotations

import asyncio

from app.news.base import NewsError


def _import_mcp():
    """Import the MCP client lazily (isolated for testability + clear failure wrapping)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    return ClientSession, streamablehttp_client


def call_tool_text(
    url: str, tool: str, arguments: dict, *, headers: dict | None = None, timeout: float = 20.0
) -> str:
    try:
        ClientSession, streamablehttp_client = _import_mcp()
    except Exception as e:  # noqa: BLE001 — SDK/native-dep import failure -> actionable error
        raise NewsError(
            f"MCP client unavailable: {e}. On Windows the mcp SDK requires pywin32 (installed "
            "with the backend deps) — reinstall the backend and fully restart the server."
        ) from e

    async def _run() -> str:
        async with streamablehttp_client(url, headers=headers or {}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments=arguments)
                parts = [
                    getattr(c, "text", "")
                    for c in (result.content or [])
                    if getattr(c, "type", "") == "text"
                ]
                return "\n".join(p for p in parts if p)

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout))
    except Exception as e:  # noqa: BLE001 — any transport/protocol/timeout error -> NewsError
        raise NewsError(f"MCP call failed: {e}") from e
