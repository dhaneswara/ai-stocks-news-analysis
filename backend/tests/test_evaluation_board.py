from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def test_empty_board(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    board = service.build_board(store, Settings())
    assert board.companies == []


def test_company_rollup_with_mixed_results(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.9, sentiment="bullish",
                            entry_price=100.0)
    # 1d hit (score 90), 5d miss (score 10); 20d still pending (no eval row)
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 1, 90.0)
    store.record_eval("AAPL", "2026-06-01", 5, "2026-06-08", 96.0, -4.0, 0, 10.0)

    board = service.build_board(store, Settings())
    assert len(board.companies) == 1
    comp = board.companies[0]
    assert comp.rollup.ticker == "AAPL"
    assert comp.rollup.n_calls == 1
    assert comp.rollup.n_matured == 2
    assert comp.rollup.hit_rate == 50.0
    assert comp.rollup.avg_score == 50.0
    assert comp.rollup.grade == "Mixed"
    assert comp.rollup.latest_recommendation == "buy"
    # the call carries three horizon results, one of them pending
    statuses = {r.horizon: r.status for r in comp.calls[0].results}
    assert statuses == {1: "final", 5: "final", 20: "pending"}


def test_rollup_none_until_matured(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="MSFT", call_date="2026-06-06", provider="a", model="m",
                            recommendation="hold", confidence=0.5, sentiment="neutral",
                            entry_price=400.0)
    comp = service.build_board(store, Settings()).companies[0]
    assert comp.rollup.n_matured == 0
    assert comp.rollup.hit_rate is None and comp.rollup.avg_score is None
    assert comp.rollup.grade is None


def test_overconfident_when_misses_more_confident(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    # A confident SELL that was wrong, and a low-confidence BUY that was right.
    store.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.95, sentiment="bearish",
                            entry_price=100.0)
    store.record_eval("NVDA", "2026-06-01", 1, "2026-06-02", 105.0, 5.0, 0, 0.0)  # miss, conf .95
    store.upsert_prediction(ticker="NVDA", call_date="2026-06-02", provider="a", model="m",
                            recommendation="buy", confidence=0.40, sentiment="bullish",
                            entry_price=105.0)
    store.record_eval("NVDA", "2026-06-02", 1, "2026-06-03", 110.0, 4.76, 1, 95.0)  # hit, conf .40
    comp = service.build_board(store, Settings()).companies[0]
    assert comp.rollup.overconfident is True


def test_board_threads_source_through_records(tmp_path):
    from app.evaluation.service import build_board
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                confidence=0.8, sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, recommendation="buy", source="llm_fast")
    store.upsert_prediction(**base, recommendation="sell", source="technical")
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 1, 90.0)  # llm_fast only
    board = build_board(store, Settings())
    comp = board.companies[0]
    by = {(c.call_date, c.source): c for c in comp.calls}
    assert by[("2026-06-01", "llm_fast")].results[0].status == "final"
    assert by[("2026-06-01", "technical")].results[0].status == "pending"
    assert comp.rollup.n_calls == 2
    assert comp.rollup.hit_rate == 100.0  # 1 matured llm_fast hit; technical still pending
