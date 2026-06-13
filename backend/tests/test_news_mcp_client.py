"""The MCP import is isolated in `_import_mcp` so its failure (e.g. a stale process missing
pywin32's DLL bootstrap on Windows) surfaces as an actionable NewsError, not a bare
ModuleNotFoundError that reaches the user as a cryptic "No module named 'pywintypes'"."""
import pytest

from app.news import mcp_client
from app.news.base import NewsError


def test_call_tool_text_wraps_mcp_import_failure(monkeypatch):
    def boom():
        raise ModuleNotFoundError("No module named 'pywintypes'")

    monkeypatch.setattr(mcp_client, "_import_mcp", boom)
    with pytest.raises(NewsError) as ei:
        mcp_client.call_tool_text("https://example/mcp", "tool", {})
    msg = str(ei.value)
    assert "MCP client unavailable" in msg       # actionable wrapper, not the bare import error
    assert "pywintypes" in msg                   # underlying cause preserved
    assert "MCP call failed" not in msg          # never reached the (network) call path
