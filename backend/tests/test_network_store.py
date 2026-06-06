from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph
from app.network.store import load_graph, save_graph


def test_graph_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier")], built=1)
    save_graph(g, cache)
    loaded = load_graph(cache, "focus")
    assert loaded is not None and loaded.edges[0].target == "TSM"
    assert load_graph(cache, "other") is None
