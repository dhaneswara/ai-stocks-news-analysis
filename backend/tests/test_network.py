from app.analysis.network import compute_network_signal
from app.models.schemas import GraphEdge, NetworkConfig, StockScore


def _score(ticker, net, direction="hold"):
    return StockScore(ticker=ticker, name=ticker, price=1.0, change_pct=0.0,
                      score=10.0, direction=direction, net=net)


def _edge(target, type, sentiment="neutral", weight=1.0, confidence=1.0):
    return GraphEdge(source="X", target=target, type=type, sentiment=sentiment,
                     weight=weight, confidence=confidence)


def test_supplier_moves_with_neighbour():
    idx = {"S": _score("S", net=-0.8, direction="sell")}
    sig = compute_network_signal("X", [_edge("S", "supplier")], idx, NetworkConfig())
    assert sig.signed < 0  # bearish supplier drags X down


def test_competitor_flips_sign():
    idx = {"C": _score("C", net=0.8, direction="buy")}
    sig = compute_network_signal("X", [_edge("C", "competitor")], idx, NetworkConfig())
    assert sig.signed < 0  # a strong competitor is bearish for X


def test_event_term_applies_without_scored_neighbour():
    sig = compute_network_signal("X", [_edge("Z", "partner", sentiment="positive")], {}, NetworkConfig())
    assert sig.signed > 0 and sig.influences[0].neighbour_direction == "unknown"


def test_signed_and_intensity_are_clamped():
    idx = {f"N{i}": _score(f"N{i}", net=-1.0, direction="sell") for i in range(5)}
    edges = [_edge(f"N{i}", "supplier", sentiment="negative") for i in range(5)]
    sig = compute_network_signal("X", edges, idx, NetworkConfig())
    assert -1.0 <= sig.signed <= 0.0 and 0.0 <= sig.intensity <= 1.0
    assert sig.signed == -1.0  # five strong-bearish edges clamp the floor


from app.analysis.network import apply_network
from app.models.schemas import KnowledgeGraph, ScreenBoard, Settings


def _board(*scores):
    return ScreenBoard(as_of="t", scope="all", scanned=len(scores), items=list(scores))


def test_apply_network_noop_when_no_graph():
    board = _board(_score("AAPL", net=0.0))
    out = apply_network(board, KnowledgeGraph(), Settings())
    assert out.items[0].network is None and out.items[0].direction == "hold"


def test_apply_network_tilts_hold_to_sell():
    # AAPL is a borderline HOLD; a strongly bearish supplier should tilt it to SELL.
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    out = apply_network(board, graph, Settings())
    aapl = next(i for i in out.items if i.ticker == "AAPL")
    assert aapl.direction == "sell" and aapl.network is not None
    assert aapl.network.reasons and aapl.components.get("network", 0) > 0


def test_apply_network_cap_cannot_flip_strong_buy():
    # A strong technical BUY must survive one bearish network edge (tilt, not override).
    board = _board(
        _score("NVDA", net=0.9, direction="buy"),
        _score("INTC", net=0.8, direction="buy"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="NVDA", target="INTC", type="competitor", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    out = apply_network(board, graph, Settings())
    nvda = next(i for i in out.items if i.ticker == "NVDA")
    assert nvda.direction == "buy"  # capped weight tilts but does not flip
