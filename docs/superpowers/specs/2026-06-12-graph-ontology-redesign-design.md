# Graph ontology redesign — design

**Date:** 2026-06-12
**Goal:** Replace the split graph world (auto-built news "focus" graph + import overlay feeding
scores; per-company saved explorations feeding nothing) with **named ontologies**: the user
builds a graph on the canvas, saves it under a chosen name, and marks exactly **one ontology
active** — that active ontology is the single graph behind every network-signal consumer in
the app. Plus two canvas features: add custom **company** nodes, and add/remove a graph
company to/from the **watchlist**.

## Decisions (user-confirmed)

- **No fallback:** when no ontology is active (or it's empty), there is **no network signal**
  — scores degrade to pure technical. Nothing hidden feeds analysis.
- **Retire the news-graph machinery:** the daily focus-graph LLM build, `POST
  /api/graph/rebuild`, the focus snapshot, and the import overlay's direct score feeding all
  go away. News extraction survives only inside **Expand neighbours** (live per-company
  extraction, unchanged). Import sets remain stored as reusable building blocks merged into
  the canvas via the existing MergePreview.
- **No migration:** existing per-root saved graphs are dropped (start fresh). Their store and
  endpoints are removed.
- Manual edits and merged imports now DO feed scores — once saved into the active ontology.
  (Reverses the earlier "manual edits are exploration-only" rule, deliberately.)

## Data model & storage (backend)

New Cache-KV namespace in `app/network/store.py`, mirroring the existing saved-graph idiom:

- `ontology:<NAME>` — JSON list of `OntologyVersion`, newest first, capped at 5 versions,
  ~permanent TTL.
- `ontology:__index__` — list of ontology names.
- `ontology:__active__` — the active ontology's name (empty/absent = none active).

Schemas (replacing `SavedGraphVersion`/`SavedGraphSummary`):

- `OntologyVersion { name, saved_at, expanded: list[str], graph: KnowledgeGraph }`
- `OntologySummary { name, versions: list[str], node_count, edge_count, active: bool }`
  (counts from the latest version).

Name rules: trimmed, 1–40 chars, unique case-insensitively (saving "nvidia" when "Nvidia"
exists updates "Nvidia"). Store functions: `save_ontology` (create-or-update; pushes a
version), `load_ontology(name, version?)`, `list_ontologies`, `delete_ontology(name,
version?)`, `get_active`/`set_active(name | None)`, and **`active_graph(cache) ->
KnowledgeGraph`** — the active ontology's latest graph, or an empty `KnowledgeGraph` when
none. Deleting an ontology entirely (or its last version) clears the active pointer if it
pointed there.

## API

- `GET  /api/graph/ontologies` → `list[OntologySummary]`
- `POST /api/graph/ontologies` (body `OntologyVersion`, `saved_at` server-set) → saved version.
  Create-or-update; "save as" is saving under a different name. **If the saved name is the
  active ontology, re-bake the Discover snapshot** (`apply_network` with the new graph).
- `GET  /api/graph/ontologies/{name}?version=` → `OntologyVersion` (404 unknown)
- `DELETE /api/graph/ontologies/{name}?version=` → `{deleted: bool}`
- `GET  /api/graph/active` → `{name: string | null}`
- `PUT  /api/graph/active` (body `{name: string | null}`) → 404 on unknown name; on change,
  **re-bake the Discover snapshot immediately** so NET scores flip without a rescan.

Removed: `POST /api/graph/rebuild`, `GET/POST /api/graph/saved*`, and `GET /api/graph`'s
focus/overlay semantics — `GET /api/graph` now returns the **active ontology's graph**
(`scope=imported` variant removed; the import-set endpoints `POST /api/graph/import`,
`GET/DELETE /api/graph/imports*`, `GET /api/graph/imports/{id}` stay as-is). Frontend
follows: `api.getOverlay`/`useOverlay` are removed and the Import tab lists/merges sets only
(MergePreview already works off `GET /api/graph/imports/{id}`).

## Scoring cutover

Every `effective_graph(cache, "focus")` consumer switches to `active_graph(cache)`:

1. `screener/service.score_one` (Dashboard score + snapshot path)
2. `api/routes._persist_rescan` (Discover rescan POST + SSE stream)
3. `services/analysis_service.gather_stock_context` (fast + deep LLM prompts)
4. `analysis/agent.app_signals` tool (deep analysis)
5. `network/runner.run` — drops `build_graph`+`save_graph`; becomes re-bake-only:
   `apply_network(board, active_graph(cache), settings)` (daily cron after the screener job).
6. `api/routes.get_graph` (display).

`effective_graph`, `load_overlay`-as-scoring-source, `build_graph`'s daily/focus mode, and the
focus snapshot read/write paths are deleted (`build_company_graph` for Expand stays).
`NetworkConfig.focus_top_n` becomes unused and is removed from the Settings UI (schema field
kept for settings-file compatibility). An empty active graph short-circuits exactly like
today's no-edges case — no new code paths in `apply_network`/`incident_edges`.

## Graph page UX (frontend)

- **Ontology header zone** (canvas toolbar): current ontology name field + **Save** (update
  that name) / **Save as** / **New** (clear canvas + name), dirty marker. Save with an empty
  name prompts for one.
- **Sidebar "Saved" tab → "Ontologies"**: rows show name, node/edge counts, **ACTIVE** badge;
  actions per row: Load, **Set active**, Delete; version history kept (load/delete a version,
  as today). A "None (network signal off)" row allows deactivating.
- **Page open:** restored canvas (localStorage explorer state) wins; otherwise the active
  ontology loads; otherwise empty.
- **Status hint:** whenever the canvas isn't the saved state of the active ontology (different
  name, or dirty), a muted line shows "Analysis currently uses ⟨active-name⟩" / "…uses no
  network signal".
- Workflow itself (empty canvas → Start from a company → Expand neighbours → Import/merge →
  right-click edits) is unchanged.

## Custom company nodes

Right-click (canvas or node) → **"Add company…"**: ticker (required, format
`^[A-Za-z][A-Za-z0-9.\-]{0,9}$`, upper-cased) + optional display name. Creates a node with
**id = TICKER** and `node_meta { label, kind: "company", source: "manual" }` — i.e. a real
company node, not a `man:` concept: it can be expanded (live extraction), influences scoring
via incident edges once the ontology is active, and supports the watchlist action. No remote
existence check (same liberal policy as the Dashboard ticker input; a bad ticker just yields
"no relationships found" on expand). Board-known tickers keep their score colouring; unknown
companies render neutral.

## Watchlist from the graph

For company nodes (id not prefixed `man:`/`ext:`): the node side-panel and the right-click
menu get **☆ Add to watchlist / ★ Remove from watchlist**, via the shared `useWatchlist`
hook (frontend-only; same dedup/guards as the Dashboard star).

## Testing

- **Backend:** ontology store CRUD + version cap + case-insensitive names + active pointer
  (set/clear-on-delete); `active_graph` empty/none behavior; each cutover site reads the
  active ontology (score_one, rescan persist, gather_stock_context, agent tool, runner);
  re-bake on activate and on save-of-active; ontology API happy/404/validation paths;
  removed endpoints return 404.
- **Frontend:** save / save-as / new flows + dirty marker; activate from the sidebar (ACTIVE
  badge, deactivate row); page-open precedence (restored > active > empty); status hint;
  add-company node (id/meta, validation); watchlist toggle on company vs concept nodes.

## Consequences & out of scope

- On ship, **NET components and network rows go quiet** until the first ontology is built and
  activated (chosen cutover behavior). The Evaluation page's historical `network` rows are
  unaffected (already recorded).
- Existing saved per-root graphs and the focus snapshot become unreachable data in the cache
  (harmless KV rows); no cleanup pass.
- Out of scope: multi-ontology blending, sharing/export of ontologies (beyond existing import
  JSON), automatic enrichment jobs.
