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
