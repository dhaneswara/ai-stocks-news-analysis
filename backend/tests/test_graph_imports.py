from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, NodeMeta
from app.network.store import (
    add_import_set, delete_import_set, list_import_sets, load_import_graph,
)


def _edge(s, t, ty="partner"):
    return GraphEdge(source=s, target=t, type=ty, origin="imported")


def test_import_set_add_list_delete(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="imported", nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")])
    s = add_import_set("set one", g, cache, created_at="2026-06-07T00:00:00+00:00")
    assert s.edge_count == 1
    assert [x.id for x in list_import_sets(cache)] == [s.id]
    loaded = load_import_graph(s.id, cache)
    assert loaded is not None and loaded.edges[0].source == "AAPL"
    assert delete_import_set(s.id, cache) is True
    assert list_import_sets(cache) == []
    assert load_import_graph(s.id, cache) is None


def test_import_set_load_graph_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(
        scope="imported", nodes=["NVDA", "ext:openai"],
        edges=[_edge("NVDA", "ext:openai")],
        node_meta={"ext:openai": NodeMeta(label="OpenAI", source="imported")},
    )
    s = add_import_set("ai set", g, cache, created_at="2026-06-07T01:00:00+00:00")
    loaded = load_import_graph(s.id, cache)
    assert loaded is not None
    assert loaded.node_meta["ext:openai"].label == "OpenAI"
    assert loaded.edges[0].target == "ext:openai"


def test_delete_import_set_returns_false_for_unknown(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    assert delete_import_set("nope", cache) is False


def test_multiple_import_sets_listed_in_order(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g1 = KnowledgeGraph(scope="imported", edges=[_edge("AAPL", "TSM")])
    g2 = KnowledgeGraph(scope="imported", edges=[_edge("MSFT", "NVDA")])
    s1 = add_import_set("first", g1, cache, created_at="2026-06-07T00:00:00+00:00")
    s2 = add_import_set("second", g2, cache, created_at="2026-06-07T02:00:00+00:00")
    ids = [x.id for x in list_import_sets(cache)]
    assert ids == [s1.id, s2.id]
    assert delete_import_set(s1.id, cache) is True
    assert [x.id for x in list_import_sets(cache)] == [s2.id]
