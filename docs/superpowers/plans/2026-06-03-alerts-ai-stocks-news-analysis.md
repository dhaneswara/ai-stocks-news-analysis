# Scheduled Buy/Sell Alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scheduled `python -m app.alerts` command that checks the watchlist for indicator-based buy/sell triggers and sends deduplicated Telegram alerts (enriched with best-effort LLM reasoning), plus a Settings UI to configure it.

**Architecture:** A new `app/alerts/` package — pure rule evaluation, a SQLite dedup store, a pluggable notifier (Telegram/log), and a runner that ties them to the existing data/analysis layers — driven by a CLI. Config lives in the existing `Settings` (SQLite, masked token). Reuses `get_stock_data` and `run_analysis`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx, SQLite, pytest (backend); React/TS, Vitest (frontend).

**Reference spec:** `docs/superpowers/specs/2026-06-02-alerts-design.md`. Built on `master`. Run backend tests from `backend/` via `.venv/Scripts/python.exe -m pytest ...` (shell activation does NOT persist across tool calls). Frontend gate is `npm run build` (= `tsc -b && vite build`) + `npx vitest run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/schemas.py` (modify) | Add `AlertConfig`, `RuleHit`, `Settings.alerts`. |
| `backend/app/config/settings_store.py` (modify) | Mask/merge `alerts.telegram_bot_token`. |
| `backend/app/alerts/__init__.py` | Package marker. |
| `backend/app/alerts/rules.py` | Pure `evaluate_rules(stock, rsi_low, rsi_high) -> list[RuleHit]`. |
| `backend/app/alerts/state.py` | `AlertState` SQLite dedup store. |
| `backend/app/alerts/notifier.py` | `Notifier` protocol, `TelegramNotifier`, `LogNotifier`, `build_notifier`. |
| `backend/app/alerts/runner.py` | `run_alerts(...)` orchestration. |
| `backend/app/alerts/__main__.py` | CLI entry. |
| `backend/app/api/routes.py` (modify) | `POST /api/alerts/test`. |
| `backend/README.md` (modify) | Alerts usage + scheduling docs. |
| `frontend/src/types.ts` (modify) | `AlertConfig` + `Settings.alerts`. |
| `frontend/src/api/client.ts` (modify) | `testAlert()`. |
| `frontend/src/pages/Settings.tsx` (modify) | Alerts config section. |
| `backend/tests/test_*` | One test module per new unit. |

---

## Task 1: Schema + settings masking for alerts

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/config/settings_store.py`
- Test: `backend/tests/test_alert_schema.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_alert_schema.py`**
```python
from app.config.settings_store import mask_settings, merge_settings
from app.models.schemas import AlertConfig, RuleHit, Settings


def test_settings_has_alert_defaults():
    s = Settings()
    assert s.alerts.enabled is False
    assert s.alerts.channel == "telegram"
    assert s.alerts.rsi_low == 30
    assert s.alerts.rsi_high == 70


def test_rule_hit_model():
    h = RuleHit(ticker="AAPL", rule_id="golden_cross", action="buy", candle_date="2026-06-01", message="x")
    assert h.action == "buy"


def test_mask_hides_telegram_token():
    s = Settings()
    s.alerts.telegram_bot_token = "secret-token"
    masked = mask_settings(s)
    assert masked.alerts.telegram_bot_token == "****"
    assert s.alerts.telegram_bot_token == "secret-token"  # original untouched


def test_merge_preserves_telegram_token_when_masked():
    existing = Settings()
    existing.alerts.telegram_bot_token = "real-token"
    incoming = Settings()
    incoming.alerts.telegram_bot_token = "****"
    merged = merge_settings(existing, incoming)
    assert merged.alerts.telegram_bot_token == "real-token"
```

- [ ] **Step 2: Run, confirm it FAILS** (`ImportError: cannot import name 'AlertConfig'`).
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_alert_schema.py -v`

- [ ] **Step 3: Edit `backend/app/models/schemas.py`** — add these two models immediately **before** the `class Settings(BaseModel):` definition (after `IndicatorParams`):
```python
class AlertConfig(BaseModel):
    enabled: bool = False
    channel: Literal["telegram", "log"] = "telegram"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    rsi_low: float = 30.0
    rsi_high: float = 70.0


class RuleHit(BaseModel):
    ticker: str
    rule_id: str
    action: Literal["buy", "sell"]
    candle_date: str
    message: str
```
And add this field to `class Settings` (after `indicator_params`):
```python
    alerts: AlertConfig = Field(default_factory=AlertConfig)
```

- [ ] **Step 4: Edit `backend/app/config/settings_store.py`** — in `mask_settings`, before `return masked`, add:
```python
    if masked.alerts.telegram_bot_token:
        masked.alerts.telegram_bot_token = MASK
```
And in `merge_settings`, before `return merged`, add:
```python
    if merged.alerts.telegram_bot_token == MASK:
        merged.alerts.telegram_bot_token = existing.alerts.telegram_bot_token
```

- [ ] **Step 5: Run the new test (4 pass) and the full suite (no regressions).**
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_alert_schema.py -v` then `.venv/Scripts/python.exe -m pytest -q`
Expected: 4 new pass; full suite green (48 + 4 = 52).

- [ ] **Step 6: Commit**
```bash
git add backend/app/models/schemas.py backend/app/config/settings_store.py backend/tests/test_alert_schema.py
git commit -m "feat(backend): add AlertConfig/RuleHit schema and token masking

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Rule evaluation (pure)

**Files:**
- Create: `backend/app/alerts/__init__.py` (empty)
- Create: `backend/app/alerts/rules.py`
- Test: `backend/tests/test_rules.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_rules.py`**
```python
from app.alerts.rules import evaluate_rules
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    PriceSummary,
    StockData,
)


def _pts(values):
    return [IndicatorPoint(time=f"2026-06-0{i+1}", value=v) for i, v in enumerate(values)]


def _stock(rsi=None, sma50=None, sma200=None, last_date="2026-06-02"):
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="t",
        price=PriceSummary(current=1.0, change=0.0, change_pct=0.0),
        candles=[Candle(time="2026-06-01", open=1, high=1, low=1, close=1, volume=1),
                 Candle(time=last_date, open=1, high=1, low=1, close=1, volume=1)],
        fundamentals=Fundamentals(),
        indicators=Indicators(rsi14=_pts(rsi or []), sma50=_pts(sma50 or []), sma200=_pts(sma200 or [])),
        news=[],
    )


def test_golden_cross_fires_buy():
    hits = evaluate_rules(_stock(sma50=[9, 11], sma200=[10, 10]))
    assert [(h.rule_id, h.action) for h in hits] == [("golden_cross", "buy")]
    assert hits[0].candle_date == "2026-06-02"


def test_death_cross_fires_sell():
    hits = evaluate_rules(_stock(sma50=[11, 9], sma200=[10, 10]))
    assert [(h.rule_id, h.action) for h in hits] == [("death_cross", "sell")]


def test_no_cross_when_persisting():
    # sma50 already above sma200 on both bars -> no crossover event
    hits = evaluate_rules(_stock(sma50=[12, 13], sma200=[10, 10]))
    assert hits == []


def test_rsi_oversold_fires_buy():
    hits = evaluate_rules(_stock(rsi=[35, 28]))
    assert [(h.rule_id, h.action) for h in hits] == [("rsi_oversold", "buy")]


def test_rsi_overbought_fires_sell():
    hits = evaluate_rules(_stock(rsi=[65, 72]))
    assert [(h.rule_id, h.action) for h in hits] == [("rsi_overbought", "sell")]


def test_rsi_no_fire_when_already_below():
    hits = evaluate_rules(_stock(rsi=[25, 26]))
    assert hits == []


def test_short_series_skipped():
    hits = evaluate_rules(_stock(rsi=[28], sma50=[11], sma200=[10]))
    assert hits == []


def test_custom_thresholds():
    hits = evaluate_rules(_stock(rsi=[45, 39]), rsi_low=40, rsi_high=80)
    assert [(h.rule_id) for h in hits] == ["rsi_oversold"]
```

- [ ] **Step 2: Run, confirm it FAILS** (`ModuleNotFoundError: app.alerts.rules`).
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_rules.py -v`

- [ ] **Step 3: Create empty `backend/app/alerts/__init__.py`, then `backend/app/alerts/rules.py`**
```python
from __future__ import annotations

from app.models.schemas import RuleHit, StockData


def evaluate_rules(stock: StockData, rsi_low: float = 30.0, rsi_high: float = 70.0) -> list[RuleHit]:
    """Detect crossover events on the latest bar (stateless: latest vs prior point)."""
    hits: list[RuleHit] = []
    ind = stock.indicators
    date = stock.candles[-1].time if stock.candles else ""

    rsi = ind.rsi14
    if len(rsi) >= 2:
        prev, curr = rsi[-2].value, rsi[-1].value
        if prev >= rsi_low and curr < rsi_low:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="rsi_oversold", action="buy",
                                candle_date=date, message=f"RSI(14) crossed below {rsi_low:g} ({curr:.1f}) — oversold."))
        elif prev <= rsi_high and curr > rsi_high:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="rsi_overbought", action="sell",
                                candle_date=date, message=f"RSI(14) crossed above {rsi_high:g} ({curr:.1f}) — overbought."))

    s50, s200 = ind.sma50, ind.sma200
    if len(s50) >= 2 and len(s200) >= 2:
        p50, c50 = s50[-2].value, s50[-1].value
        p200, c200 = s200[-2].value, s200[-1].value
        if p50 <= p200 and c50 > c200:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="golden_cross", action="buy",
                                candle_date=date, message="SMA50 crossed above SMA200 (golden cross)."))
        elif p50 >= p200 and c50 < c200:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="death_cross", action="sell",
                                candle_date=date, message="SMA50 crossed below SMA200 (death cross)."))

    return hits
```

- [ ] **Step 4: Run, confirm 8 pass.**
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_rules.py -v`

- [ ] **Step 5: Commit**
```bash
git add backend/app/alerts/__init__.py backend/app/alerts/rules.py backend/tests/test_rules.py
git commit -m "feat(backend): add pure indicator rule evaluation for alerts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Dedup state store

**Files:**
- Create: `backend/app/alerts/state.py`
- Test: `backend/tests/test_alert_state.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_alert_state.py`**
```python
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
```

- [ ] **Step 2: Run, confirm it FAILS** (`ModuleNotFoundError: app.alerts.state`).

- [ ] **Step 3: Create `backend/app/alerts/state.py`**
```python
from __future__ import annotations

import sqlite3
import time


class AlertState:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS alert_log "
            "(ticker TEXT, rule_id TEXT, candle_date TEXT, sent_at REAL, "
            "PRIMARY KEY (ticker, rule_id, candle_date))"
        )
        self._conn.commit()

    def was_alerted(self, ticker: str, rule_id: str, candle_date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alert_log WHERE ticker = ? AND rule_id = ? AND candle_date = ?",
            (ticker, rule_id, candle_date),
        ).fetchone()
        return row is not None

    def mark(self, ticker: str, rule_id: str, candle_date: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO alert_log (ticker, rule_id, candle_date, sent_at) VALUES (?, ?, ?, ?)",
            (ticker, rule_id, candle_date, time.time()),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run, confirm 3 pass.**

- [ ] **Step 5: Commit**
```bash
git add backend/app/alerts/state.py backend/tests/test_alert_state.py
git commit -m "feat(backend): add SQLite alert dedup state store

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Notifier (Telegram / log)

**Files:**
- Create: `backend/app/alerts/notifier.py`
- Test: `backend/tests/test_notifier.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_notifier.py`**
```python
from app.alerts.notifier import LogNotifier, TelegramNotifier, build_notifier
from app.models.schemas import AlertConfig


def test_telegram_send_posts_expected_payload(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr("app.alerts.notifier.httpx.post", fake_post)
    TelegramNotifier("TOKEN", "CHAT").send("Title", "Body")
    assert captured["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert captured["json"]["chat_id"] == "CHAT"
    assert "Title" in captured["json"]["text"] and "Body" in captured["json"]["text"]


def test_build_notifier_telegram_when_configured():
    cfg = AlertConfig(channel="telegram", telegram_bot_token="t", telegram_chat_id="c")
    assert isinstance(build_notifier(cfg), TelegramNotifier)


def test_build_notifier_log_when_dry_run():
    cfg = AlertConfig(channel="telegram", telegram_bot_token="t", telegram_chat_id="c")
    assert isinstance(build_notifier(cfg, dry_run=True), LogNotifier)


def test_build_notifier_log_when_unconfigured():
    cfg = AlertConfig(channel="telegram")  # no token/chat
    assert isinstance(build_notifier(cfg), LogNotifier)


def test_build_notifier_env_fallback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    cfg = AlertConfig(channel="telegram")  # empty in settings
    notifier = build_notifier(cfg)
    assert isinstance(notifier, TelegramNotifier)
    assert notifier.token == "env-tok"
    assert notifier.chat_id == "env-chat"


def test_log_notifier_does_not_raise():
    LogNotifier().send("t", "b")
```

- [ ] **Step 2: Run, confirm it FAILS** (`ModuleNotFoundError: app.alerts.notifier`).

- [ ] **Step 3: Create `backend/app/alerts/notifier.py`**
```python
from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from app.models.schemas import AlertConfig

logger = logging.getLogger("alerts")


class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class LogNotifier:
    def send(self, title: str, body: str) -> None:
        logger.info("ALERT %s | %s", title, body)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, title: str, body: str) -> None:
        resp = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": f"<b>{title}</b>\n{body}", "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()


def build_notifier(cfg: AlertConfig, dry_run: bool = False) -> Notifier:
    if dry_run or cfg.channel == "log":
        return LogNotifier()
    token = cfg.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if cfg.channel == "telegram" and token and chat_id:
        return TelegramNotifier(token, chat_id)
    logger.warning("Alerts enabled but Telegram is not fully configured; using log notifier.")
    return LogNotifier()
```

- [ ] **Step 4: Run, confirm 6 pass.**

- [ ] **Step 5: Commit**
```bash
git add backend/app/alerts/notifier.py backend/tests/test_notifier.py
git commit -m "feat(backend): add Telegram/log notifier with env fallback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Alert runner (orchestration)

**Files:**
- Create: `backend/app/alerts/runner.py`
- Test: `backend/tests/test_runner.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_runner.py`**
```python
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
    # Second run: same candle -> deduped
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
```

- [ ] **Step 2: Run, confirm it FAILS** (`ModuleNotFoundError: app.alerts.runner`).

- [ ] **Step 3: Create `backend/app/alerts/runner.py`**
```python
from __future__ import annotations

import logging

from app.alerts.notifier import Notifier
from app.alerts.rules import evaluate_rules
from app.alerts.state import AlertState
from app.config.cache import Cache
from app.models.schemas import DISCLAIMER, Settings
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data

logger = logging.getLogger("alerts")
ALERT_PERIOD = "1y"


def _reasoning(ticker: str, period: str, settings: Settings, cache: Cache) -> str:
    try:
        result = run_analysis(ticker, period, settings, cache)
        return f"LLM ({result.current_recommendation.upper()}): {result.overall_summary}"
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM reasoning unavailable for %s: %s", ticker, exc)
        return ""


def run_alerts(
    settings: Settings,
    cache: Cache,
    state: AlertState,
    notifier: Notifier,
    with_llm: bool = True,
    period: str = ALERT_PERIOD,
) -> dict:
    if not settings.alerts.enabled:
        logger.info("Alerts are disabled; nothing to do.")
        return {"enabled": False, "checked": 0, "sent": 0}

    checked = 0
    sent = 0
    for ticker in settings.watchlist:
        checked += 1
        try:
            stock = get_stock_data(ticker, period, settings.indicator_params, cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", ticker, exc)
            continue
        for hit in evaluate_rules(stock, settings.alerts.rsi_low, settings.alerts.rsi_high):
            if state.was_alerted(hit.ticker, hit.rule_id, hit.candle_date):
                continue
            reasoning = _reasoning(ticker, period, settings, cache) if with_llm else ""
            title = f"{hit.action.upper()} signal — {stock.company_name} ({ticker})"
            body = hit.message + (f"\n\n{reasoning}" if reasoning else "") + f"\n\n{DISCLAIMER}"
            try:
                notifier.send(title, body)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send alert for %s/%s: %s", ticker, hit.rule_id, exc)
                continue
            state.mark(hit.ticker, hit.rule_id, hit.candle_date)
            sent += 1
            logger.info("Sent %s alert for %s (%s)", hit.action, ticker, hit.rule_id)
    return {"enabled": True, "checked": checked, "sent": sent}
```

- [ ] **Step 4: Run, confirm 4 pass + full suite green.**
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_runner.py -v` then `.venv/Scripts/python.exe -m pytest -q`

- [ ] **Step 5: Commit**
```bash
git add backend/app/alerts/runner.py backend/tests/test_runner.py
git commit -m "feat(backend): add alert runner (rules + dedup + best-effort LLM + notify)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: CLI entry + README scheduling docs

**Files:**
- Create: `backend/app/alerts/__main__.py`
- Modify: `backend/README.md`
- Test: `backend/tests/test_alerts_cli.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_alerts_cli.py`**
```python
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
```

- [ ] **Step 2: Run, confirm it FAILS** (`ModuleNotFoundError: app.alerts.__main__`).

- [ ] **Step 3: Create `backend/app/alerts/__main__.py`**
```python
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.alerts.notifier import build_notifier
from app.alerts.runner import run_alerts
from app.alerts.state import AlertState
from app.deps import DATA_DIR, DB_PATH, get_cache, get_settings_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.alerts", description="Run watchlist buy/sell alerts.")
    parser.add_argument("--dry-run", action="store_true", help="Log alerts instead of sending them.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM reasoning enrichment.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    cache = get_cache()
    state = AlertState(DB_PATH)
    notifier = build_notifier(settings.alerts, dry_run=args.dry_run)
    summary = run_alerts(settings, cache, state, notifier, with_llm=not args.no_llm)
    logging.getLogger("alerts").info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm it passes.**
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_alerts_cli.py -v`

- [ ] **Step 5: Append an "Alerts" section to `backend/README.md`** (after the Endpoints section):
```markdown
## Scheduled alerts

Check your watchlist for buy/sell triggers and send Telegram alerts:

    python -m app.alerts            # evaluate + send
    python -m app.alerts --dry-run  # log instead of sending
    python -m app.alerts --no-llm   # skip LLM reasoning

Configure in the frontend Settings → Alerts (enable, Telegram bot token + chat id,
RSI thresholds), or via env vars `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. Alerts are
deduplicated per (ticker, rule, day).

### Schedule it daily (Windows Task Scheduler)

Create a Basic Task → Daily (e.g. 5:30 PM, after US close) → Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.alerts`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry running the same command from `backend/`.)
```

- [ ] **Step 6: Commit**
```bash
git add backend/app/alerts/__main__.py backend/tests/test_alerts_cli.py backend/README.md
git commit -m "feat(backend): add alerts CLI and scheduling docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `POST /api/alerts/test` endpoint

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_alerts.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_api_alerts.py`**
```python
from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_settings_store
from app.main import app


def _client(tmp_path):
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    store = SettingsStore(str(tmp_path / "s.db"))
    app.dependency_overrides[get_settings_store] = lambda: store
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()


def test_alerts_test_requires_telegram_config(tmp_path):
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"  # no token/chat
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_alerts_test_ok(tmp_path, monkeypatch):
    class FakeNotifier:
        def send(self, title, body):
            return None

    monkeypatch.setattr(routes, "build_notifier", lambda cfg, dry_run=False: FakeNotifier())
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"
    s.alerts.telegram_bot_token = "t"
    s.alerts.telegram_chat_id = "c"
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_alerts_test_reports_send_failure(tmp_path, monkeypatch):
    class BoomNotifier:
        def send(self, title, body):
            raise RuntimeError("bad token")

    monkeypatch.setattr(routes, "build_notifier", lambda cfg, dry_run=False: BoomNotifier())
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"
    s.alerts.telegram_bot_token = "t"
    s.alerts.telegram_chat_id = "c"
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.json()["ok"] is False
    assert "bad token" in resp.json()["message"]
```

- [ ] **Step 2: Run, confirm it FAILS** (404 — route not defined).

- [ ] **Step 3: Edit `backend/app/api/routes.py`** — add `import os` at the top (with the stdlib imports), add this import with the other `app.*` imports:
```python
from app.alerts.notifier import build_notifier
```
Then append this route at the end of the file:
```python
@router.post("/alerts/test")
def test_alert(store: SettingsStore = Depends(get_settings_store)) -> dict:
    cfg = store.load().alerts
    token = cfg.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if cfg.channel == "telegram" and not (token and chat_id):
        return {"ok": False, "message": "Telegram bot token and chat id are required."}
    try:
        build_notifier(cfg).send("Test alert", "Alerts are configured correctly. (Not financial advice.)")
        return {"ok": True, "message": "Test alert sent."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
```

- [ ] **Step 4: Run, confirm 3 pass + full suite green.**
Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_alerts.py -v` then `.venv/Scripts/python.exe -m pytest -q`

- [ ] **Step 5: Commit**
```bash
git add backend/app/api/routes.py backend/tests/test_api_alerts.py
git commit -m "feat(backend): add POST /api/alerts/test endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Frontend — Alerts settings section

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Edit `frontend/src/types.ts`** — add the `AlertConfig` interface and an `alerts` field on `Settings`:
```ts
export interface AlertConfig {
  enabled: boolean;
  channel: 'telegram' | 'log';
  telegram_bot_token: string;
  telegram_chat_id: string;
  rsi_low: number;
  rsi_high: number;
}
```
Add to the `Settings` interface (after `indicator_params`):
```ts
  alerts: AlertConfig;
```

- [ ] **Step 2: Edit `frontend/src/api/client.ts`** — add to the `api` object (after `testProvider`):
```ts
  testAlert: () => http<TestResult>('/alerts/test', { method: 'POST' }),
```

- [ ] **Step 3: Replace `frontend/src/pages/Settings.tsx`** with the version below (adds the Alerts section; the provider section is unchanged):
```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useProviders, useSaveSettings, useSettings } from '../hooks/queries';
import type { AlertConfig, ProviderId, Settings as SettingsT, TestResult } from '../types';

export default function Settings() {
  const settingsQuery = useSettings();
  const providers = useProviders();
  const save = useSaveSettings();
  const [form, setForm] = useState<SettingsT | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [alertTest, setAlertTest] = useState<TestResult | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settingsQuery.data) setForm(structuredClone(settingsQuery.data));
  }, [settingsQuery.data]);

  if (!form) return <p className="muted">Loading settings…</p>;

  const active = form.active_provider;
  const cfg = form.providers[active];
  const update = (next: Partial<SettingsT>) => { setForm({ ...form, ...next }); setSaved(false); };
  const updateCfg = (patch: Partial<typeof cfg>) =>
    update({ providers: { ...form.providers, [active]: { ...cfg, ...patch } } });
  const updateAlerts = (patch: Partial<AlertConfig>) => update({ alerts: { ...form.alerts, ...patch } });

  const onSave = () => save.mutate(form, { onSuccess: () => setSaved(true) });
  const onTest = async () => {
    setTest(null);
    await save.mutateAsync(form);
    setTest(await api.testProvider(active));
  };
  const onTestAlert = async () => {
    setAlertTest(null);
    await save.mutateAsync(form);
    setAlertTest(await api.testAlert());
  };

  return (
    <div className="panel" style={{ maxWidth: 640 }}>
      <h3 style={{ marginTop: 0 }}>Provider settings</h3>

      <div className="field">
        <label>Active provider</label>
        <select value={active} onChange={(e) => update({ active_provider: e.target.value as ProviderId })}>
          {(providers.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.configured ? ' ✓' : ''}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Model</label>
        <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
      </div>

      {active === 'ollama' ? (
        <div className="field">
          <label>Base URL</label>
          <input value={cfg.base_url} onChange={(e) => updateCfg({ base_url: e.target.value })} placeholder="http://localhost:11434" />
        </div>
      ) : (
        <div className="field">
          <label>API key (leave as **** to keep the saved key)</label>
          <input type="password" value={cfg.api_key} onChange={(e) => updateCfg({ api_key: e.target.value })} placeholder="paste API key" />
        </div>
      )}

      <div className="field">
        <label>Watchlist (comma-separated)</label>
        <input
          value={form.watchlist.join(', ')}
          onChange={(e) => update({ watchlist: e.target.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) })}
        />
      </div>

      <h3>Alerts</h3>
      <div className="field">
        <label>
          <input
            type="checkbox"
            checked={form.alerts.enabled}
            onChange={(e) => updateAlerts({ enabled: e.target.checked })}
          />{' '}
          Enable scheduled buy/sell alerts
        </label>
      </div>
      {form.alerts.enabled && (
        <>
          <div className="field">
            <label>Telegram bot token (leave as **** to keep the saved token)</label>
            <input
              type="password"
              value={form.alerts.telegram_bot_token}
              onChange={(e) => updateAlerts({ telegram_bot_token: e.target.value })}
              placeholder="123456:ABC-..."
            />
          </div>
          <div className="field">
            <label>Telegram chat id</label>
            <input
              value={form.alerts.telegram_chat_id}
              onChange={(e) => updateAlerts({ telegram_chat_id: e.target.value })}
              placeholder="e.g. 987654321"
            />
          </div>
          <div className="row">
            <div className="field">
              <label>RSI low (buy)</label>
              <input type="number" value={form.alerts.rsi_low} onChange={(e) => updateAlerts({ rsi_low: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>RSI high (sell)</label>
              <input type="number" value={form.alerts.rsi_high} onChange={(e) => updateAlerts({ rsi_high: Number(e.target.value) })} />
            </div>
          </div>
          <button className="secondary" onClick={onTestAlert} disabled={save.isPending}>Send test alert</button>
          {alertTest && <span className={alertTest.ok ? 'muted' : 'error'} style={{ marginLeft: 8 }}>{alertTest.ok ? '✓ ' : '✗ '}{alertTest.message}</span>}
        </>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 16 }}>
        <button onClick={onSave} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
        <button className="secondary" onClick={onTest} disabled={save.isPending}>Test connection</button>
        {saved && <span className="muted">Saved.</span>}
        {test && <span className={test.ok ? 'muted' : 'error'}>{test.ok ? '✓ ' : '✗ '}{test.message}</span>}
      </div>
      {save.isError && <p className="error">Save failed: {(save.error as Error).message}</p>}
    </div>
  );
}
```

- [ ] **Step 4: Verify (from `frontend/`)**
- `npm run build` → succeeds (type-check + bundle).
- `npx vitest run` → still 7 passed.

- [ ] **Step 5: Commit**
```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "feat(frontend): add Alerts settings section + test-alert button

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Done — alerts complete

Configure Telegram in Settings → Alerts (or env vars), then schedule
`python -m app.alerts` daily. Verify setup with the "Send test alert" button or
`python -m app.alerts --dry-run`.
