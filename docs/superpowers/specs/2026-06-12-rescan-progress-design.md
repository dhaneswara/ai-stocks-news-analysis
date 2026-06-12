# Live rescan progress — design

**Date:** 2026-06-12
**Problem:** "Rescan all" (Discover) and "Full Discover rescan" (Evaluation) fire a single
`POST /api/screen/rescan` that synchronously scans ~500 tickers for minutes. The UI can only
flip the button label to "Scanning…" until the response lands — the user cannot tell a
working scan from a hung one.

## Approach

Stream the scan over SSE, exactly like the watchlist LLM batch
(`GET /api/analyze/watchlist/stream`). Rejected alternatives: a progress-polling endpoint
(introduces server-side mutable progress state and a second transport pattern) and a
frontend-only spinner/elapsed timer (does not distinguish working from hung — the actual
complaint).

## Backend

- `app/screener/service.py`: refactor `run_scan` into a generator `iter_scan(scope, settings,
  cache)` that yields one `ScanProgress(ticker, scanned, total, skipped)` per ticker —
  emitted **before** the fetch, so a stalled ticker is identifiable by name — and the
  finished `ScreenBoard` as the final item. `run_scan` consumes it unchanged in signature
  (still used by the CLI, the scheduled runner and the POST route).
- `app/models/schemas.py`: `RescanEvent` — `type: tick|done|error`, `ticker`, `scanned`,
  `total`, `skipped`, `message`.
- `app/api/routes.py`: extract the persist step (graph blend + sector merge + save) shared by
  the POST route into `_persist_rescan`. New `GET /screen/rescan/stream?sector=` streams
  `tick` per ticker, persists the snapshot, then emits a terminal `done` (final counts);
  scan-aborting exceptions surface as an in-stream `error` event (EventSource cannot read an
  HTTP error body). `POST /screen/rescan` is kept as-is for API compatibility.
- Disconnect semantics (same trade-off as the LLM batch): closing the stream cancels the scan
  at its next yield and **nothing is saved** — per-ticker price data is cached, so a redo
  after a stop/refresh is fast.

## Frontend

- `api/client.ts`: `streamRescan(sector, handlers)` mirroring `streamWatchlistRun`; the
  unused `api.rescan` POST helper and `useRescan` mutation are removed.
- New `hooks/useRescanRun.ts` (mirrors `useWatchlistRun`): state `{phase, ticker, scanned,
  total, skipped, summary, stopped, message}` with `start(sector?, onDone?)`, `stop()`,
  `reset()`. Invalidates the `['screen']` query only on `done` (a stopped/failed scan saved
  nothing). `onDone` carries the rescan→snapshot chain, registered in the provider so it
  survives page navigation.
- `state/watchlistRunState.tsx`: `rescan` becomes the run-state object instead of a mutation;
  `rescanAndSnapshot` passes the snapshot as `onDone`.
- UI: both buttons show `Scanning… 123/503`; a status line shows the in-flight ticker and
  skip count; a **Stop** button appears while scanning; `RunIndicator` masthead chip shows
  `Rescan 123/503` with the in-flight ticker in its tooltip.

## Testing

- Backend: `iter_scan` progress sequence + final board; stream endpoint happy path (ticks,
  done, snapshot persisted) and mid-scan failure (`event: error`).
- Frontend: `useRescanRun` unit tests (mirroring `useWatchlistRun`'s); `streamRescan` client
  tests; `EvaluationCommandBar` and `RunIndicator` tests updated from mutation mocks to
  stream-handler mocks.
