from app.models.schemas import (
    CompanyEvaluation,
    CompanyRollup,
    EvaluationBoard,
    EvaluationConfig,
    HorizonResult,
    PredictionRecord,
    Settings,
)


def test_evaluation_config_defaults():
    cfg = EvaluationConfig()
    assert cfg.enabled is True
    assert cfg.horizons == [1, 5, 20]
    assert cfg.hold_band_pct == 2.0
    assert cfg.score_scale_pct == 5.0


def test_settings_includes_evaluation_and_round_trips():
    s = Settings()
    assert s.evaluation.enabled is True
    again = Settings.model_validate_json(s.model_dump_json())
    assert again.evaluation.horizons == [1, 5, 20]


def test_response_models_construct():
    hr = HorizonResult(horizon=5, status="final", eval_date="2026-06-12",
                       return_pct=3.0, hit=True, score=80.0)
    rec = PredictionRecord(ticker="AAPL", call_date="2026-06-05", provider="anthropic",
                           model="m", recommendation="buy", confidence=0.8,
                           sentiment="bullish", entry_price=200.0, results=[hr])
    roll = CompanyRollup(ticker="AAPL", n_calls=1, n_matured=1, hit_rate=100.0,
                         avg_score=80.0, grade="Strong", overconfident=False,
                         latest_recommendation="buy", latest_call_date="2026-06-05")
    board = EvaluationBoard(as_of="t", companies=[CompanyEvaluation(rollup=roll, calls=[rec])])
    assert board.companies[0].rollup.grade == "Strong"
    assert board.companies[0].calls[0].results[0].hit is True


def test_horizon_result_pending_defaults():
    hr = HorizonResult(horizon=1)
    assert hr.status == "pending" and hr.return_pct is None and hr.hit is None
