from app.alerts import __main__ as cli


def test_main_runs_and_returns_zero(monkeypatch):
    calls = {}

    def fake_run_alerts(settings, cache, state, notifier, with_llm=True, period="1y"):
        calls["with_llm"] = with_llm
        return {"enabled": True, "checked": 0, "sent": 0}

    captured = {}

    def fake_build_notifier(cfg, dry_run=False):
        captured["dry_run"] = dry_run
        return object()

    monkeypatch.setattr(cli, "run_alerts", fake_run_alerts)
    monkeypatch.setattr(cli, "build_notifier", fake_build_notifier)
    assert cli.main(["--dry-run", "--no-llm"]) == 0
    assert captured["dry_run"] is True
    assert calls["with_llm"] is False
