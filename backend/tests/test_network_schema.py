from app.models.schemas import (
    GraphEdge, KnowledgeGraph, NetworkConfig, NetworkInfluence, NetworkSignal,
    Settings, StockScore,
)


def test_graph_edge_defaults():
    e = GraphEdge(source="AAPL", target="GOOGL", type="partner")
    assert e.sentiment == "neutral" and e.weight == 0.5 and e.confidence == 0.5


def test_knowledge_graph_round_trip():
    g = KnowledgeGraph(scope="focus", nodes=["AAPL"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative")
    ], built=1, skipped=0)
    again = KnowledgeGraph.model_validate_json(g.model_dump_json())
    assert again.edges[0].target == "TSM" and again.built == 1


def test_network_signal_and_influence():
    sig = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.3, influences=[
        NetworkInfluence(neighbour="TSM", type="supplier", edge_sentiment="negative",
                         neighbour_direction="sell", signed=-0.3, reason="supplier TSM (bearish)")
    ], reasons=["supplier TSM (bearish)"])
    assert sig.influences[0].neighbour == "TSM"


def test_stock_score_gains_net_and_network():
    s = StockScore(ticker="AAPL", name="Apple", price=1.0, change_pct=0.0,
                   score=10.0, direction="hold")
    assert s.net == 0.0 and s.network is None


def test_settings_has_network_defaults():
    n = Settings().network
    assert n.enabled and n.focus_top_n == 30 and n.weight == 0.5
    assert n.alpha_event == 0.6 and n.beta_state == 0.4
