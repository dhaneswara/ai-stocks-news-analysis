from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, NodeMeta
from app.network.store import (
    add_import_set, delete_import_set, effective_graph, list_import_sets,
    load_overlay, merge_graphs, save_graph,
)


def _edge(s, t, ty="partner"):
    return GraphEdge(source=s, target=t, type=ty, origin="imported")


def test_merge_graphs_unions_nodes_edges_and_meta():
    a = KnowledgeGraph(nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")])
    b = KnowledgeGraph(
        nodes=["NVDA", "ext:openai"], edges=[_edge("AAPL", "NVDA"), _edge("NVDA", "ext:openai")],
        node_meta={"ext:openai": NodeMeta(label="OpenAI", source="imported")},
    )
    out = merge_graphs(a, b)
    assert sorted(out.nodes) == ["AAPL", "NVDA", "ext:openai"]
    assert len(out.edges) == 2                       # AAPL->NVDA deduped
    assert out.node_meta["ext:openai"].label == "OpenAI"


def test_overlay_crud_and_load(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="imported", nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")])
    s = add_import_set("set one", g, cache, created_at="2026-06-07T00:00:00+00:00")
    assert s.edge_count == 1
    assert [x.id for x in list_import_sets(cache)] == [s.id]
    overlay = load_overlay(cache)
    assert overlay.edges[0].source == "AAPL"
    assert delete_import_set(s.id, cache) is True
    assert list_import_sets(cache) == []
    assert load_overlay(cache).edges == []


def test_effective_graph_merges_focus_and_overlay(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_graph(KnowledgeGraph(scope="focus", nodes=["AAPL"], edges=[_edge("AAPL", "TSM", "supplier")]), cache)
    add_import_set("o", KnowledgeGraph(nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")]),
                   cache, created_at="2026-06-07T00:00:00+00:00")
    eff = effective_graph(cache, "focus")
    assert eff.scope == "focus"
    assert len(eff.edges) == 2
    assert {e.target for e in eff.edges} == {"TSM", "NVDA"}
