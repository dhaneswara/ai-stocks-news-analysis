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
    assert "Market cap 3.00T" in out  # human-readable, not 3000000000000.0
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


from app.models.schemas import (
    GraphEdge, KnowledgeGraph, NetworkInfluence, NetworkSignal, StockScore, TruthPost, MarketMood,
)


def test_opportunity_score_formats(monkeypatch):
    monkeypatch.setattr(chat_tools, "score_one", lambda t, s, c: StockScore(
        ticker=t, name="NVIDIA", price=120.0, change_pct=1.7, score=71.0,
        direction="buy", reasons=["RSI 40 (recovering)", "above SMA50"]))
    out = chat_tools._tool_opportunity_score({"ticker": "NVDA"}, _ctx())
    assert "71/100" in out and "buy" in out and "RSI 40 (recovering)" in out


def test_opportunity_score_requires_ticker():
    assert chat_tools._tool_opportunity_score({}, _ctx()).startswith("ERROR")


def test_network_signal_disabled():
    ctx = _ctx()
    ctx.settings.network.enabled = False
    assert "disabled" in chat_tools._tool_network_signal({"ticker": "NVDA"}, ctx)


def test_network_signal_no_edges(monkeypatch):
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: KnowledgeGraph())
    assert "no active ontology" in chat_tools._tool_network_signal({"ticker": "NVDA"}, _ctx())


def test_network_signal_lists_influences(monkeypatch):
    graph = KnowledgeGraph(nodes=["NVDA", "AMD"],
                           edges=[GraphEdge(source="NVDA", target="AMD", type="competitor")])
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: graph)
    monkeypatch.setattr(chat_tools, "combined_base_index", lambda c: {})
    monkeypatch.setattr(chat_tools, "incident_edges", lambda t, e, sym: graph.edges)
    monkeypatch.setattr(chat_tools, "compute_network_signal", lambda t, e, b, cfg: NetworkSignal(
        ticker="NVDA", signed=-0.3, intensity=0.4,
        influences=[NetworkInfluence(neighbour="AMD", name="AMD", type="competitor",
                                     neighbour_direction="buy", reason="AMD strength")]))
    out = chat_tools._tool_network_signal({"ticker": "NVDA"}, _ctx())
    assert "competitor AMD" in out and "AMD strength" in out


def test_geopolitics_disabled():
    ctx = _ctx()
    ctx.settings.truth_signal.enabled = False
    assert "disabled" in chat_tools._tool_geopolitics({}, ctx)


def test_geopolitics_summarizes(monkeypatch):
    monkeypatch.setattr(chat_tools.truth_social, "fetch_recent_posts_cached",
                        lambda lh, url, cache: [TruthPost(id="1", created_at="2026-06-12", content="Tariffs incoming on chips")])
    monkeypatch.setattr(chat_tools.political, "summarize_market_mood",
                        lambda posts, prov, model, pid, cache: MarketMood(lean="risk_off", confidence=0.6, summary="Tariff risk."))
    monkeypatch.setattr(chat_tools.political, "find_mentions", lambda posts, t, name: [])
    out = chat_tools._tool_geopolitics({"ticker": "NVDA"}, _ctx())
    assert "risk_off" in out and "Tariff risk." in out


def test_track_record_none_when_no_history(monkeypatch):
    monkeypatch.setattr(chat_tools, "build_track_record_block", lambda t, store, s: None)
    ctx = ChatContext(settings=Settings(), cache=Cache(":memory:"),
                      provider=FakeProvider([]), prediction_store=object())
    assert "no matured evaluation history" in chat_tools._tool_track_record({"ticker": "NVDA"}, ctx)


def test_network_signal_unavailable_on_error(monkeypatch):
    graph = KnowledgeGraph(nodes=["NVDA"],
                           edges=[GraphEdge(source="NVDA", target="AMD", type="competitor")])
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: graph)
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(chat_tools, "incident_edges", _boom)
    out = chat_tools._tool_network_signal({"ticker": "NVDA"}, _ctx())
    assert "network signal unavailable" in out


def test_geopolitics_unavailable_on_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("archive down")
    monkeypatch.setattr(chat_tools.truth_social, "fetch_recent_posts_cached", _boom)
    out = chat_tools._tool_geopolitics({}, _ctx())
    assert "geopolitics signal unavailable" in out


from app.models.schemas import ScreenBoard


def test_portfolio_board_no_snapshot(monkeypatch):
    monkeypatch.setattr(chat_tools, "load_snapshot", lambda c, scope: None)
    assert "no scan results yet" in chat_tools._tool_portfolio_board({}, _ctx())


def test_portfolio_board_ranks_and_filters(monkeypatch):
    board = ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="NVDA", name="NVIDIA", price=120.0, change_pct=1.0, score=80.0,
                   direction="buy", sector="Technology"),
        StockScore(ticker="KO", name="Coca-Cola", price=60.0, change_pct=0.1, score=40.0,
                   direction="hold", sector="Consumer"),
    ])
    monkeypatch.setattr(chat_tools, "load_snapshot", lambda c, scope: board)
    out = chat_tools._tool_portfolio_board({"direction": "buy"}, _ctx())
    assert "NVDA (NVIDIA) 80/100 buy" in out
    assert "KO" not in out  # filtered out by direction


def test_portfolio_board_filters_by_sector_on_portfolio(monkeypatch):
    board = ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="NVDA", name="NVIDIA", price=120.0, change_pct=1.0, score=80.0,
                   direction="buy", sector="Technology"),
        StockScore(ticker="KO", name="Coca-Cola", price=60.0, change_pct=0.1, score=40.0,
                   direction="hold", sector="Consumer"),
    ])
    monkeypatch.setattr(chat_tools, "load_snapshot", lambda c, scope: board)
    out = chat_tools._tool_portfolio_board({"sector": "Technology"}, _ctx())
    assert "NVDA" in out and "KO" not in out


def test_ontology_overview_empty(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_active_ontology", lambda c: None)
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: KnowledgeGraph())
    assert "no active ontology" in chat_tools._tool_ontology_overview({}, _ctx())


def test_ontology_overview_lists_companies(monkeypatch):
    graph = KnowledgeGraph(nodes=["NVDA", "AMD", "ext:TSMC"],
                           edges=[GraphEdge(source="NVDA", target="AMD", type="competitor")])
    monkeypatch.setattr(chat_tools, "get_active_ontology", lambda c: "Semis")
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: graph)
    out = chat_tools._tool_ontology_overview({}, _ctx())
    assert "Semis" in out and "NVDA" in out and "competitor" in out


def test_watchlist_lists_tickers():
    ctx = _ctx()
    ctx.settings.watchlist = ["AAPL", "msft"]
    assert "AAPL, MSFT" in chat_tools._tool_watchlist({}, ctx)


def test_registry_has_ten_tools():
    assert {t.name for t in TOOLS} == {
        "get_stock", "price_window", "search_news", "geopolitics", "opportunity_score",
        "network_signal", "portfolio_board", "track_record", "ontology_overview", "watchlist",
    }
    assert TOOL_BY_NAME["get_stock"].run is chat_tools._tool_get_stock
