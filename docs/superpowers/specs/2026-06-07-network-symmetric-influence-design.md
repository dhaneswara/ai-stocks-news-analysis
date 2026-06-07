# Type-Aware Symmetric Network Influence — Design Spec

**Date:** 2026-06-07
**Status:** Approved (design)

## Goal

Make a knowledge-graph relationship influence the BUY/SELL/HOLD of **both** endpoint
companies when the relationship is of a *mutual* type (competitor, partner, other),
while keeping *directional* types (supplier, customer, owner, subsidiary) one-way as they
are today. The change works retroactively on existing extracted edges and imported
overlays — no data migration.

## Background — current behavior

The network signal is **directed**. A company `T` is scored only by edges where
`T == source`; the edge's `target` is treated as the neighbour whose technical condition
and the edge's news sentiment flow into `T`. Three runtime sites select edges this way:

- `apply_network` (`backend/app/analysis/network.py`) → Discover board + scheduled
  bake-in (`runner.py`, `routes.py`). Buckets `edges_by_source[e.source]`.
- `score_one` (`backend/app/screener/service.py`) → Dashboard single-ticker score.
  `[e for e in graph.edges if e.source == ticker]`.
- `analysis_service` (`backend/app/services/analysis_service.py`) → LLM-analysis network
  context. Same `e.source == ticker` filter.

The core scorer `compute_network_signal(ticker, edges, base_index, cfg)` hardcodes
`neighbour = e.target` for every edge.

Consequence: an asymmetric edge `PLTR → NVDA` moves PLTR's score (NVDA is its neighbour)
but has **zero** effect on NVDA, because no edge has `source == NVDA`. This is the gap the
feature closes for mutual relationship types.

## Decisions

1. **Mutual types:** `competitor`, `partner`, `other`. (`other` is included because
   imported ontologies and manual links frequently use it for a generic "affected by".)
2. **Directional types (unchanged):** `supplier`, `customer`, `owner`, `subsidiary`.
3. **Config-gated, default ON.** A new `NetworkConfig.symmetric_types` list defaults to the
   three mutual types. An **empty list reproduces today's pure-directed behavior** (clean
   off-switch and regression guard). Default-on means scores reflect the new behavior
   immediately on the next rescore.
4. **No Settings UI control** — consistent with the other `NetworkConfig` knobs
   (`alpha_event`, `beta_state`, …), which are config-only and not surfaced in the UI.

## The scoring rule

For a company `T`, the set of edges that score it becomes:

- **Forward** — every edge where `T == e.source` (any type). *Identical to today.*
- **Reverse** — edges where `T == e.target` **and** `e.type ∈ symmetric_types`. *New.*

For each scoring edge the **neighbour is the other endpoint**, and the per-edge terms gain
one directional twist, because the edge's news `sentiment` was judged from the **source's**
perspective:

| term         | forward (`T == source`) | reverse (`T == target`) |
|--------------|-------------------------|-------------------------|
| neighbour    | `e.target`              | `e.source`              |
| event (news) | `event`                 | `tsign · event`         |
| state (tech) | `tsign · nb_net`        | `tsign · nb_net`        |

where `tsign = −1` for `competitor`, else `+1`, and `event = {positive:+1, neutral:0,
negative:−1}[e.sentiment]`.

Rationale for the reverse event sign: a competitor's *good* news lands **negative** on its
rival, so the event term must invert (`tsign·event`); for `partner` / `other` the news lands
**same-sign**. The state term already uses `tsign` and is symmetric, so it is unchanged
between directions.

**Forward is byte-for-byte identical to today** (`is_reverse == False` ⇒ neighbour = target,
event term = event), so directional types and the source side of mutual types do not
regress. The only new contributions are reverse edges for the three mutual types.

Per-edge formula (unchanged shape):

```
w           = e.weight * e.confidence
event_term  = (tsign * event) if is_reverse else event
state_term  = tsign * nb_net
e_signed    = w * (cfg.alpha_event * event_term + cfg.beta_state * state_term)
e_intensity = w * max(abs(event_term), abs(state_term))
```

## Architecture / components

### Backend

- **`schemas.py` — `NetworkConfig`**
  Add `symmetric_types: list[RelationType] = ["competitor", "partner", "other"]`.
  Pydantic's default backfills legacy persisted settings automatically (same mechanism that
  backfilled the DeepSeek provider), so no migration is required.

- **`network.py` — new helper `incident_edges`**
  ```
  def incident_edges(ticker, edges, symmetric) -> list[GraphEdge]:
      # forward: ticker is source (any type); reverse: ticker is target AND type ∈ symmetric.
      # self-loops (source == target) are counted once (forward branch; elif guards the reverse).
  ```
  Single source of truth for "which edges score this ticker", shared by all three sites.

- **`network.py` — `compute_network_signal`**
  For each edge derive `is_reverse = (e.source != ticker)`,
  `neighbour_id = e.source if is_reverse else e.target`, look up `nb` by `neighbour_id`,
  and apply the event-sign twist above. `NetworkInfluence.neighbour` / `reason` reference the
  real other-endpoint. Signature is unchanged: `(ticker, edges, base_index, cfg)`.

- **`network.py` — `apply_network`**
  Replace the `edges_by_source` bucket with a per-row `incident_edges(s.ticker, graph.edges,
  set(cfg.symmetric_types))` call. Graph sizes are small (focus cap ~30 companies ×
  `max_edges_per_company`), so per-row selection is negligible and keeps one code path.
  Idempotency is preserved (blend still re-blends from `base_score`/`base_net`).

- **`screener/service.py` & `services/analysis_service.py`**
  Replace the `e.source == ticker` comprehension with
  `incident_edges(ticker, graph.edges, set(settings.network.symmetric_types))`.

### Frontend

- **`types.ts` — `NetworkConfig`**
  Mirror `symmetric_types: RelationType[]` so it survives a Settings load→save round-trip.
- **Test fixtures** (`useWatchlist.test.tsx`, `Dashboard.test.tsx`, `Settings.test.tsx`)
  Add `symmetric_types: ['competitor','partner','other']` to the inline `network` literals.
- **No UI control, no graph-viz change.** Network displays (Discover / Dashboard /
  NetworkPanel / GraphSidebar) already render `network.influences`; they improve
  automatically because `neighbour` is now the true other-endpoint.

## Data flow

`effective_graph("focus")` (saved focus snapshot ∪ imported overlay) is unchanged — it is
still the only graph scoring reads. The change is purely in *edge selection* and the
*per-edge neighbour/sign* inside the scorer. Manual/merged explorer edits remain
exploration-only and continue not to feed scores.

## Edge cases & compatibility

- **Both directions present** (`PLTR→NVDA` and `NVDA→PLTR` as separate edges): both count as
  independent evidence for each endpoint; bounded by the existing `[−1, 1]` clamp on
  `signed`/`intensity`.
- **Self-loop** (`source == target`): counted once.
- **Neighbour absent from the scored board**: `nb_net = 0` (state term drops out), only the
  event term contributes — same as today.
- **`symmetric_types == []`**: exactly today's directed behavior (regression guard).
- **Baked board snapshot**: reflects the new behavior after the next rescore
  (scheduler/refresh). No manual migration step.

## Testing strategy

- `incident_edges`: forward selects all types; reverse selects only symmetric types;
  a `supplier` reverse is excluded; self-loop counted once.
- `compute_network_signal`: competitor-reverse inverts the event sign; partner/other-reverse
  keep the sign; forward output is unchanged vs. the current baseline.
- `apply_network`: a `partner` edge tilts **both** endpoints; a `supplier` edge tilts only
  the source; idempotency holds; `symmetric_types=[]` reproduces the old result.
- Integration: a target company receives a non-empty `network` signal via `score_one` and
  `analysis_service` for a reverse symmetric edge.
- Frontend: fixtures updated; `tsc -b` + `vitest` green.

## Out of scope

- No Settings UI control for `symmetric_types`.
- No graph-canvas visual change for reverse-scoring edges.
- No change to graph extraction/import (reverse influence is computed at read time, not
  materialized as new edges).
- No data migration.
