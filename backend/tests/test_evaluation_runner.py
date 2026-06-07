from app.evaluation import runner
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def test_disabled_returns_early(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    settings = Settings()
    settings.evaluation.enabled = False
    summary = runner.run_evaluation(store, settings)
    assert summary == {"enabled": False, "tickers": 0, "evaluated": 0, "pending": 0}


def test_enabled_delegates_to_evaluate_pending(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    captured = {}

    def fake_eval(s, settings, *, persist=True):
        captured["persist"] = persist
        return {"tickers": 1, "evaluated": 2, "pending": 1}

    monkeypatch.setattr(runner, "evaluate_pending", fake_eval)
    summary = runner.run_evaluation(store, Settings(), dry_run=True)
    assert summary["enabled"] is True and summary["evaluated"] == 2
    assert captured["persist"] is False  # dry-run disables persistence
