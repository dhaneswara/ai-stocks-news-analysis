from app.alerts.state import AlertState


def test_first_check_is_false_then_marked(tmp_path):
    state = AlertState(str(tmp_path / "app.db"))
    assert state.was_alerted("AAPL", "golden_cross", "2026-06-01") is False
    state.mark("AAPL", "golden_cross", "2026-06-01")
    assert state.was_alerted("AAPL", "golden_cross", "2026-06-01") is True


def test_different_candle_date_is_independent(tmp_path):
    state = AlertState(str(tmp_path / "app.db"))
    state.mark("AAPL", "golden_cross", "2026-06-01")
    assert state.was_alerted("AAPL", "golden_cross", "2026-06-02") is False


def test_mark_is_idempotent(tmp_path):
    state = AlertState(str(tmp_path / "app.db"))
    state.mark("AAPL", "rsi_oversold", "2026-06-01")
    state.mark("AAPL", "rsi_oversold", "2026-06-01")  # no error on repeat
    assert state.was_alerted("AAPL", "rsi_oversold", "2026-06-01") is True
