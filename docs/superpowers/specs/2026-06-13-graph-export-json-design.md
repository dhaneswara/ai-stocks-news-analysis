# Export working graph to JSON — design

**Date:** 2026-06-13
**Status:** Approved (pending spec review)

## Problem

A user builds a knowledge graph (an ontology) on one machine and wants the same graph
on another machine running the same app. Today there is an *import* path
(`POST /api/graph/import` → `normalize_import`, plus the Graph page's Import tab with paste
and file-upload), but no way to get an existing graph *out* of the app as a file. The user
asked for the ability to export an existing graph to JSON so it can be imported elsewhere.

## Scope

- **What is exported:** the **working canvas** on the Graph page — whatever `KnowledgeGraph`
  is currently loaded (a loaded ontology or unsaved work). Triggered by a new **Export**
  button next to Save / Save as / New.
- **Round-trip target:** reuse the **existing Import tab**. Export emits the import-model JSON
  shape that `normalize_import` already accepts, so on the other machine the user uploads the
  file in the Import tab → it lands as an import-set overlay → merge into canvas → Save → Set
  active (the steps they already use). No backend changes.

Out of scope (YAGNI): exporting a specific saved ontology server-side, exporting *all*
ontologies as a backup bundle, a faithful lossless ontology round-trip, and clipboard copy.

## Format

The export is a single JSON object in the shape `normalize_import` consumes (the same shape
`chatGptPrompt` documents):

```json
{
  "name": "<ontology name>",
  "as_of": "<from graph.as_of, may be empty>",
  "nodes": [{ "id": "NVDA", "label": "NVIDIA", "kind": "company" }],
  "edges": [{ "source": "NVDA", "target": "TSM", "type": "supplier",
             "sentiment": "positive", "weight": 0.8, "confidence": 0.7,
             "evidence": "...", "url": "..." }]
}
```

The Import tab's file-upload path (`onFile` → `JSON.parse` → `onImport(name, parsed)` →
`api.importGraph` → `POST /api/graph/import`, where `model = body.get("payload", body)`)
already accepts a bare model object, so this file imports with no new endpoint.

### Mapping `KnowledgeGraph` → import model

- `name`: the current `ontologyName` (passed through verbatim; may be empty).
- `as_of`: `graph.as_of` passed through (empty → backend defaults to `now` on import).
- `nodes`: for each id in `graph.nodes` →
  `{ id, label: node_meta[id]?.label ?? id, kind: node_meta[id]?.kind ?? '' }`.
  Native ticker nodes carry no `node_meta`, so their label becomes the ticker itself, which the
  resolver re-resolves to a ticker node on import.
- `edges`: project each `GraphEdge` to `{ source, target, type, sentiment, weight, confidence,
  evidence, url }`. Drop `origin` and the per-edge `as_of` — neither is part of the import
  shape.

## Accepted lossiness

Chosen explicitly (reuse-import-tab over a faithful new-ontology path):

- Tickers are re-resolved on import; `man:` and `ext:` nodes land as `ext:` nodes.
- Edge `origin` (extracted / imported / manual) is lost — everything re-imports as `imported`.
- Relationship types squash to the six canonical types + `other`.
- Imports are capped at 1000 edges; self-loops, unresolved, and duplicate edges are dropped by
  `normalize_import`.
- The file lands as an import-set overlay, **not** directly as a saved/active ontology — the
  user runs the existing merge → Save → Set active flow.

Export emits everything faithfully; the import side does the clamping/dropping above.

## Components

1. **`frontend/src/lib/graphExport.ts`** (pure, no I/O):
   - `toImportModel(graph: KnowledgeGraph, name: string): ImportModel` — the mapping above.
   - `exportFilename(name: string): string` — slug of the name + `.json`; fallback `graph.json`.
   - An `ImportModel` type for the returned object.

2. **`frontend/src/lib/download.ts`** (the only DOM side-effect, kept out of the pure module):
   - `downloadText(filename: string, text: string, mime = 'application/json'): void` — builds a
     `Blob`, creates an anchor, clicks it, revokes the object URL.

3. **`frontend/src/pages/Graph.tsx`**:
   - An **Export** button in `.ontology-bar` after "New", `className="secondary"`, with a
     `title` tooltip ("Download this graph as JSON to import on another machine").
   - Disabled when the canvas is empty (`!working || working.nodes.length === 0` — the Save guard).
   - Click handler:
     `downloadText(exportFilename(ontologyName), JSON.stringify(toImportModel(working, ontologyName), null, 2))`.

## Data flow

Working canvas (`KnowledgeGraph` in Graph state) → `toImportModel` → `JSON.stringify` →
`downloadText` → browser saves `<name>.json`.
On machine B: Import tab → upload file → existing import flow → import-set overlay →
merge into canvas → Save → Set active.

## Error handling

- `toImportModel` is total — it never throws (missing `node_meta` falls back to id/empty kind;
  empty graph yields empty `nodes`/`edges`).
- The Export button is disabled on an empty canvas, so there is nothing to export-and-fail.
- `downloadText` is a best-effort browser action; no app state changes, so no recovery path is
  needed.

## Testing

- **`frontend/src/lib/graphExport.test.ts`** (vitest):
  - `toImportModel`: label/kind fallback when `node_meta` is missing; edge projection drops
    `origin` and `as_of`; `name` and `as_of` pass through; empty graph → empty arrays;
    `ext:` / `man:` node ids preserved verbatim.
  - `exportFilename`: slugging, and the `graph.json` fallback for an empty/odd name.
- The `downloadText` DOM wrapper is a thin side-effect; light test (mock `URL.createObjectURL`
  and the anchor click) or omit.
