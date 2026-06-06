from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, SavedGraphVersion
from app.network.store import (
    delete_saved_graph, list_saved_graphs, load_company_graph, load_graph, save_company_graph,
    save_graph,
)


def test_graph_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier")], built=1)
    save_graph(g, cache)
    loaded = load_graph(cache, "focus")
    assert loaded is not None and loaded.edges[0].target == "TSM"
    assert load_graph(cache, "other") is None


def _ver(root, saved_at):
    return SavedGraphVersion(root=root, saved_at=saved_at,
                             graph=KnowledgeGraph(scope=f"company:{root}", nodes=[root]))


def test_saved_history_caps_and_orders(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    for i in range(6):
        save_company_graph(_ver("AAPL", f"t{i}"), cache)
    summary = next(s for s in list_saved_graphs(cache) if s.root == "AAPL")
    assert summary.versions == ["t5", "t4", "t3", "t2", "t1"]  # newest first, t0 evicted (cap 5)
    assert load_company_graph("AAPL", cache).saved_at == "t5"          # latest
    assert load_company_graph("AAPL", cache, "t3").saved_at == "t3"    # by version
    assert load_company_graph("AAPL", cache, "t0") is None             # evicted


def test_saved_root_is_upper_cased(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_company_graph(_ver("aapl", "t1"), cache)
    assert load_company_graph("AAPL", cache) is not None
    assert load_company_graph("aapl", cache) is not None  # lookup also normalizes


def test_saved_delete_version_then_root(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_company_graph(_ver("AAPL", "t1"), cache)
    save_company_graph(_ver("AAPL", "t2"), cache)
    assert delete_saved_graph("AAPL", cache, "t1") is True
    assert load_company_graph("AAPL", cache, "t1") is None
    assert load_company_graph("AAPL", cache, "t2") is not None
    assert delete_saved_graph("AAPL", cache) is True   # whole root
    assert load_company_graph("AAPL", cache) is None
    assert list_saved_graphs(cache) == []


def test_saved_load_missing_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    assert load_company_graph("ZZZZ", cache) is None
    assert delete_saved_graph("ZZZZ", cache) is False
