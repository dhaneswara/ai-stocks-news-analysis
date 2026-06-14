import app.chat.tools as chat_tools
from app.chat.tools import TOOLS, TOOL_BY_NAME, ChatContext, ChatTool
from app.config.cache import Cache
from app.models.schemas import (
    Candle, Fundamentals, IndicatorPoint, Indicators, NewsItem, PriceSummary, StockData,
)
from app.models.schemas import Settings
from tests.test_analyzer import FakeProvider


def _ctx():
    return ChatContext(settings=Settings(), cache=Cache(":memory:"),
                       provider=FakeProvider([]), prediction_store=None)


def test_chat_context_holds_dependencies():
    ctx = _ctx()
    assert ctx.settings.active_provider == "anthropic"
    assert ctx.prediction_store is None


def test_chat_tool_dataclass_fields():
    t = ChatTool("echo", "echoes", '{"q": str}', lambda args, ctx: "ok")
    assert t.name == "echo"
    assert t.run({}, None) == "ok"


def _rich_stock():
    return StockData(
        ticker="NVDA", company_name="NVIDIA Corp", as_of="2026-06-12", exchange="NASDAQ",
        sector="Technology",
        price=PriceSummary(current=120.0, change=2.0, change_pct=1.7),
        candles=[Candle(time=f"2026-05-{d:02d}", open=p, high=p, low=p, close=p, volume=1)
                 for d, p in [(1, 100.0), (4, 102.0), (5, 98.0), (6, 105.0), (7, 110.0)]],
        fundamentals=Fundamentals(market_cap=3e12, pe_ratio=45.0, eps=2.6,
                                  week52_high=140.0, week52_low=80.0),
        indicators=Indicators(rsi14=[IndicatorPoint(time="2026-05-07", value=58.3)],
                              dist_from_52wk_high_pct=-14.3),
        news=[],
    )


def test_get_stock_formats_snapshot(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_stock_data", lambda t, p, ip, c: _rich_stock())
    out = chat_tools._tool_get_stock({"ticker": "nvda"}, _ctx())
    assert "NVDA" in out and "NVIDIA Corp" in out
    assert "120.00" in out
    assert "P/E 45.0" in out
    assert "RSI14 58.3" in out


def test_get_stock_requires_ticker():
    assert chat_tools._tool_get_stock({}, _ctx()).startswith("ERROR")


def test_get_stock_missing_data_is_error(monkeypatch):
    def _boom(t, p, ip, c):
        raise ValueError("no data")
    monkeypatch.setattr(chat_tools, "get_stock_data", _boom)
    assert chat_tools._tool_get_stock({"ticker": "ZZZZ"}, _ctx()).startswith("ERROR")


def test_price_window_summarizes(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_stock_data", lambda t, p, ip, c: _rich_stock())
    out = chat_tools._tool_price_window({"ticker": "NVDA", "lookback_days": 5}, _ctx())
    assert "last 5 trading days" in out
    assert "100.00 -> 110.00" in out


def test_search_news_formats(monkeypatch):
    monkeypatch.setattr(chat_tools, "search_news", lambda q, limit=5: [
        NewsItem(title="Chip demand surges", source="Reuters", published_at="2026-06-10")])
    out = chat_tools._tool_search_news({"query": "AI chips"}, _ctx())
    assert "Chip demand surges (Reuters)" in out


def test_search_news_requires_query():
    assert chat_tools._tool_search_news({}, _ctx()).startswith("ERROR")
