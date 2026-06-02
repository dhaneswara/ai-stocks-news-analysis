# Scheduled Buy/Sell Alerts — Design

- **Date:** 2026-06-02
- **Status:** Approved (v1 scope)
- **Builds on:** the backend on `master` (data/indicators/analysis/settings/cache layers).

## Overview

A scheduled command, `python -m app.alerts`, that for each watchlist ticker fetches
price data + indicators, evaluates cheap **rule-based triggers**, and on a *fresh*
trigger sends a **Telegram** alert enriched with best-effort **LLM reasoning**.
Alerts are deduplicated so the same event isn't re-sent. The job is run by the OS
scheduler (Windows Task Scheduler / cron), typically once daily after market close.

This completes the original request's "alert on when to buy and when to sell."
It is **decision support, not financial advice** — rules are mechanical heuristics.

## Locked decisions

| Decision | Choice |
|---|---|
| Trigger | Indicator rules decide WHEN; LLM called only then for reasoning (hybrid) |
| Delivery | Telegram (Bot API), behind a `Notifier` interface for future channels |
| Execution | `python -m app.alerts` CLI run via OS scheduler |
| Config | `AlertConfig` in the existing Settings (SQLite); env-var fallback; frontend Settings section |
| LLM on fire | Reuse `run_analysis` (cached per day); best-effort, never blocks the alert |

## Trigger rules (v1; thresholds configurable)

Evaluated per ticker from the computed indicator series. "Cross" = condition holds on
the latest bar and did NOT hold on the prior bar (detected from the last two points —
stateless), so alerts fire on the *event*, not every day it persists.

| rule_id | Condition | Action |
|---|---|---|
| `rsi_oversold` | RSI(14) crosses below `rsi_low` (default 30) | buy |
| `rsi_overbought` | RSI(14) crosses above `rsi_high` (default 70) | sell |
| `golden_cross` | SMA50 crosses above SMA200 | buy |
| `death_cross` | SMA50 crosses below SMA200 | sell |

`sma50` and `sma200` series are trailing-aligned (same source close series), so their
last two points share dates and can be compared directly. RSI uses its own last two
points. Each rule requires ≥2 points in the relevant series, else it is skipped.
The event date is the latest candle's date.

## Dedup

A SQLite table `alert_log(ticker, rule_id, candle_date, sent_at)` with PK
`(ticker, rule_id, candle_date)`. Before sending, the runner checks `was_alerted(...)`;
after sending it `mark(...)`s. So an event for a given day's candle fires once, even if
the job runs multiple times that day.

## LLM reasoning (best-effort, graceful)

When a rule fires, the runner calls `run_analysis(ticker, ...)` (cached per
ticker+provider+day, so cheap) and includes a short line — the recommendation +
the first sentence(s) of the summary — in the alert. If no provider key is configured
or the LLM errors, the alert still sends with only the rule explanation. The LLM is
never on the critical path for alert delivery.

## Delivery — Telegram

- `Notifier` protocol: `send(title: str, body: str) -> None`.
- `TelegramNotifier(token, chat_id)` → `httpx.post` to
  `https://api.telegram.org/bot{token}/sendMessage` with `{chat_id, text, parse_mode:"HTML"}`.
- `LogNotifier` → logs the message (used for `--dry-run` and when alerts are enabled
  but no channel is configured).
- `build_notifier(alert_config, dry_run)` selects the implementation.

## Configuration

`AlertConfig` (new) is added to the existing `Settings` model and persisted in the same
SQLite settings store:

```jsonc
"alerts": {
  "enabled": false,
  "channel": "telegram | log",
  "telegram_bot_token": "****",   // masked on read; sentinel preserves stored value
  "telegram_chat_id": "",
  "rsi_low": 30,
  "rsi_high": 70
}
```

- `mask_settings` also masks `alerts.telegram_bot_token`; `merge_settings` preserves it
  when the incoming value is the `****` sentinel (same mechanism as provider API keys).
- Env-var fallback for headless use: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Set via the frontend **Settings → Alerts** section, or env vars.

## Data model (new)

```jsonc
// RuleHit
{ "ticker": "AAPL", "rule_id": "golden_cross", "action": "buy",
  "candle_date": "2026-06-01", "message": "SMA50 crossed above SMA200 (golden cross)." }
```
`AlertConfig` as above. No change to `StockData`/`AnalysisResult`.

## Components

```
backend/app/alerts/
  __init__.py
  rules.py        # evaluate_rules(stock, rsi_low, rsi_high) -> list[RuleHit]  (pure)
  state.py        # AlertState(db_path): was_alerted / mark  (SQLite)
  notifier.py     # Notifier protocol, TelegramNotifier, LogNotifier, build_notifier
  runner.py       # run_alerts(settings, cache, state, notifier, with_llm, dry_run) -> summary
  __main__.py     # CLI: build deps from DATA_DIR, parse --dry-run, run, log summary, exit 0
```
Plus: `models/schemas.py` (+`AlertConfig`, `RuleHit`, `Settings.alerts`),
`config/settings_store.py` (mask/merge the token), `api/routes.py`
(`POST /api/alerts/test`), and the frontend Settings section + `types.ts` + `api/client.ts`.

## API

- `POST /api/alerts/test` → builds the notifier from current settings, sends a test
  message, returns `{ok, message}` (mirrors the provider connection-test endpoint).

## Frontend (Settings → Alerts section)

Enable toggle, channel (telegram), bot token (password input, `****`-preserving),
chat id, `rsi_low`/`rsi_high` inputs, and a **Send test alert** button calling
`POST /api/alerts/test`. Reuses the existing settings save/merge flow.

## CLI & scheduling

`python -m app.alerts [--dry-run]` (run from `backend/`, or via the venv interpreter).
Reads settings, iterates the watchlist, evaluates → dedups → notifies, logs a one-line
summary per ticker, exits 0 (non-zero only on unexpected fatal error). The backend
README documents scheduling it daily after close, e.g. a Windows Task Scheduler action:
`D:\…\backend\.venv\Scripts\python.exe -m app.alerts` (Start in `…\backend`), or cron.

## Error handling

- Per-ticker failures (bad data, network) are caught and logged; the run continues.
- Notifier failure is logged per alert; dedup is only marked on a successful send, so a
  failed send retries next run.
- Alerts disabled (`enabled=false`) → the CLI logs and exits without sending.
- Missing Telegram config while enabled → falls back to `LogNotifier` with a warning.

## Testing (TDD)

- **rules.py** — constructed indicator series: golden cross fires on the crossover bar
  and NOT while persisting; death cross; RSI crossing below 30 / above 70; no-fire cases;
  multiple hits same day; <2 points skipped.
- **state.py** — first `was_alerted` is False, after `mark` it's True; different
  candle_date is independent (tmp db).
- **notifier.py** — `TelegramNotifier` posts the correct URL + payload (mocked httpx);
  `build_notifier` picks telegram vs log; `LogNotifier` doesn't raise.
- **runner.py** — orchestration with mocked `get_stock_data`/`run_analysis`/notifier/state:
  fires on trigger, dedups on repeat, LLM-failure still sends, disabled → no sends.
- **settings** — mask/merge of `telegram_bot_token`.
- **api** — `POST /api/alerts/test` ok + failure paths (mocked notifier).
- **CLI** — smoke with mocked runner (exits 0; honors `--dry-run`).

## Build order

1. Schema: `AlertConfig` + `RuleHit` + `Settings.alerts`; settings mask/merge for the token.
2. `rules.py` (TDD).
3. `state.py` (TDD).
4. `notifier.py` (TDD, mocked httpx).
5. `runner.py` (TDD, mocked deps).
6. `__main__.py` CLI + backend README scheduling docs.
7. `POST /api/alerts/test` route (TDD).
8. Frontend: `types.ts` + `api/client.ts` + Settings → Alerts section.

## Caveats

- **Not financial advice** — included verbatim in each alert. Rules are mechanical
  heuristics, not validated signals.
- Telegram bot token stored locally (gitignored data dir; masked in API/UI).
- Cost stays near zero: LLM is called only when a rule fires, and reuses the daily cache.
