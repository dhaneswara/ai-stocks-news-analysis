from app.models.schemas import ScreenBoard, ScreenerConfig, Settings, StockScore


def test_screener_config_defaults():
    cfg = ScreenerConfig()
    assert cfg.enabled is True
    assert cfg.top_n == 25
    assert cfg.rsi_low == 30.0 and cfg.rsi_high == 70.0
    assert set(cfg.weights) == {"extremes", "trend", "momentum", "volume", "catalyst"}
    assert cfg.weights["extremes"] == 1.0


def test_settings_includes_screener():
    assert Settings().screener.top_n == 25


def test_stockscore_minimal_defaults():
    s = StockScore(ticker="AAPL", name="Apple Inc.", price=200.0, change_pct=1.0,
                   score=70.0, direction="buy")
    assert s.sector == "" and s.reasons == [] and s.components == {} and s.as_of == ""


def test_screenboard_defaults():
    b = ScreenBoard()
    assert b.items == [] and b.scope == "all" and b.scanned == 0 and b.as_of == ""
