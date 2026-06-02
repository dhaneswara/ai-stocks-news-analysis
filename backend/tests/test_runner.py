from app.alerts import runner
from app.alerts.state import AlertState
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)


def _golden_cross_stock():
    pts = lambda vals: [IndicatorPoint(time=f"2026-06-0{i+1}", value=v) for i, v in enumerate(vals)]
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="t",
        price=PriceSummary(current=1.0, change=0.0, change_pct=0.0),
        candles=[Candle(time="2026-06-01", open=1, high=1, low=1, close=1, volume=1),
                 Candle(time="2026-06-02", open=1, high=1, low=1, close=1, volume=1)],
        fundamentals=Fundamentals(),
        indicators=Indicators(rsi14=pts([50, 50]), sma50=pts([9, 11]), sma200=pts([10, 10])),
        news=[],
    )


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body):
        self.sent.append((title, body))


def _settings():
    s = Settings()
    s.alerts.enabled = True
    s.alerts.channel = "log"
    s.watchlist = ["AAPL"]
    return s


def test_disabled_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "get_stock_data", lambda *a, **k: _golden_cross_stock())
    s = _settings()
    s.alerts.enabled = False
    notifier = FakeNotifier()
    summary = runner.run_alerts(s, cache=None, state=AlertState(str(tmp_path / "a.db")), notifier=notifier, with_llm=False)
    assert summary["sent"] == 0
    assert notifier.sent == []


def test_fires_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "get_stock_data", lambda *a, **k: _golden_cross_stock())
    state = AlertState(str(tmp_path / "a.db"))
    notifier = FakeNotifier()
    first = runner.run_alerts(_settings(), cache=None, state=state, notifier=notifier, with_llm=False)
    assert first["sent"] == 1
    assert "golden cross" in notifier.sent[0][1]
    second = runner.run_alerts(_settings(), cache=None, state=state, notifier=notifier, with_llm=False)
    assert second["sent"] == 0


def test_llm_failure_still_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "get_stock_data", lambda *a, **k: _golden_cross_stock())

    def boom(*a, **k):
        raise RuntimeError("no key")

    monkeypatch.setattr(runner, "run_analysis", boom)
    notifier = FakeNotifier()
    summary = runner.run_alerts(_settings(), cache=None, state=AlertState(str(tmp_path / "a.db")), notifier=notifier, with_llm=True)
    assert summary["sent"] == 1


def test_data_failure_skips_ticker(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("no data")

    monkeypatch.setattr(runner, "get_stock_data", boom)
    notifier = FakeNotifier()
    summary = runner.run_alerts(_settings(), cache=None, state=AlertState(str(tmp_path / "a.db")), notifier=notifier, with_llm=False)
    assert summary["sent"] == 0 and summary["checked"] == 1
