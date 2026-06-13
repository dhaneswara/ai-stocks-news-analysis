from app.analysis.network import compute_network_signal
from app.models.schemas import GraphEdge, NetworkConfig, StockScore


def _score(ticker, net, direction="hold"):
    return StockScore(ticker=ticker, name=ticker, price=1.0, change_pct=0.0,
                      score=10.0, direction=direction, net=net, base_net=net, base_score=10.0)


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


def test_apply_network_is_idempotent():
    # Re-applying (e.g. a sector rescan that merges already-blended rows) must NOT double-count
    # or feed blended values back in — blending always starts from base_score/base_net.
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    once = apply_network(board, graph, Settings())
    twice = apply_network(once, graph, Settings())
    a1 = next(i for i in once.items if i.ticker == "AAPL")
    a2 = next(i for i in twice.items if i.ticker == "AAPL")
    assert (a1.score, a1.net, a1.direction) == (a2.score, a2.net, a2.direction)
    assert a1.base_net == 0.0 and a1.base_score == 10.0  # base preserved across blends


def test_blend_network_into_score():
    from app.analysis.network import blend_network_into_score
    from app.models.schemas import NetworkSignal, Settings, StockScore
    s = StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold",
                   net=0.0, base_score=50.0, base_net=0.0)
    sig = NetworkSignal(ticker="AAPL", intensity=1.0, signed=1.0, influences=[],
                        reasons=["partner X (bullish)"])
    out = blend_network_into_score(s, sig, Settings())
    assert out.network is sig
    assert out.score > 50.0                 # positive intensity raised the score
    assert out.net > 0.0 and out.direction == "buy"
    assert out.components["network"] == 1.0
    assert out.reasons[0] == "partner X (bullish)"   # network reasons first


def test_network_config_defaults_symmetric_types():
    # competitor/partner/other are mutual by default; supplier/customer/owner/subsidiary are not.
    assert NetworkConfig().symmetric_types == ["competitor", "partner", "other"]
    assert "supplier" not in NetworkConfig().symmetric_types


def test_incident_edges_forward_all_reverse_symmetric_only():
    from app.analysis.network import incident_edges
    edges = [
        GraphEdge(source="A", target="X", type="partner", sentiment="neutral", weight=1, confidence=1),   # reverse + mutual -> in
        GraphEdge(source="B", target="X", type="supplier", sentiment="neutral", weight=1, confidence=1),  # reverse + directional -> out
        GraphEdge(source="X", target="C", type="supplier", sentiment="neutral", weight=1, confidence=1),  # forward (any type) -> in
    ]
    got = incident_edges("X", edges, {"partner", "competitor", "other"})
    assert {(e.source, e.target) for e in got} == {("A", "X"), ("X", "C")}


def test_incident_edges_self_loop_counted_once():
    from app.analysis.network import incident_edges
    e = GraphEdge(source="X", target="X", type="partner", sentiment="neutral", weight=1, confidence=1)
    assert incident_edges("X", [e], {"partner"}) == [e]


def test_reverse_competitor_inverts_event_sign():
    # Edge C -> X (competitor); scoring X via the reverse edge. Positive news for C is bearish for X.
    edges = [GraphEdge(source="C", target="X", type="competitor", sentiment="positive", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, {}, NetworkConfig())
    assert sig.signed < 0
    assert sig.influences[0].neighbour == "C"


def test_reverse_partner_keeps_event_sign():
    edges = [GraphEdge(source="P", target="X", type="partner", sentiment="positive", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, {}, NetworkConfig())
    assert sig.signed > 0
    assert sig.influences[0].neighbour == "P"


def test_reverse_uses_source_as_neighbour_state():
    # X is the target of a partner edge from P; P's bearish technical state drags X down.
    idx = {"P": _score("P", net=-0.8, direction="sell")}
    edges = [GraphEdge(source="P", target="X", type="partner", sentiment="neutral", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, idx, NetworkConfig())
    assert sig.signed < 0
    assert sig.influences[0].neighbour == "P" and sig.influences[0].neighbour_direction == "sell"


def test_apply_network_symmetric_edge_tilts_both_endpoints():
    # A partner edge AAA -> BBB scores AAA (forward) AND BBB (reverse).
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    out = apply_network(board, graph, Settings())
    a = next(i for i in out.items if i.ticker == "AAA")
    b = next(i for i in out.items if i.ticker == "BBB")
    assert a.network is not None and b.network is not None
    assert a.components.get("network", 0) > 0 and b.components.get("network", 0) > 0


def test_apply_network_directional_edge_skips_target():
    # A supplier edge is directional: only the source (AAA) is scored, not the target (BBB).
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="supplier", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    out = apply_network(board, graph, Settings())
    assert next(i for i in out.items if i.ticker == "BBB").network is None


def test_apply_network_empty_symmetric_types_is_directed():
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    settings = Settings()
    settings.network.symmetric_types = []
    out = apply_network(board, graph, settings)
    assert next(i for i in out.items if i.ticker == "BBB").network is None  # directed: target unscored


# ---------------------------------------------------------------------------
# New tests for re-bake / strip_network semantics
# ---------------------------------------------------------------------------

def test_apply_network_empty_graph_strips_previous_blend():
    """Re-applying with an empty graph must undo a previous blend (not leave stale values)."""
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    blended = apply_network(board, graph, Settings())
    aapl_blended = next(i for i in blended.items if i.ticker == "AAPL")
    assert aapl_blended.network is not None  # sanity: it was blended

    # Re-apply with an empty graph -> stale blend must be undone
    out = apply_network(blended, KnowledgeGraph(), Settings())
    aapl_out = next(i for i in out.items if i.ticker == "AAPL")

    assert aapl_out.network is None
    assert aapl_out.score == aapl_out.base_score
    assert aapl_out.net == aapl_out.base_net
    from app.analysis.scoring import direction_for
    assert aapl_out.direction == direction_for(aapl_out.base_net)
    assert "network" not in aapl_out.components
    # Network reason chips must be gone
    for reason in aapl_blended.network.reasons:
        assert reason not in aapl_out.reasons


def test_apply_network_resets_row_whose_edges_disappeared():
    """A row with no incident edges in the new graph is reset to base; other rows still blend."""
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
        _score("MSFT", net=0.5, direction="buy"),
        _score("ORCL", net=0.3, direction="hold"),
    )
    # First blend: AAPL->TSM edge
    graph1 = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    blended = apply_network(board, graph1, Settings())
    aapl_blended = next(i for i in blended.items if i.ticker == "AAPL")
    assert aapl_blended.network is not None

    # Re-bake with a DIFFERENT graph that only touches MSFT/ORCL
    graph2 = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="MSFT", target="ORCL", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)
    ])
    out = apply_network(blended, graph2, Settings())

    aapl_out = next(i for i in out.items if i.ticker == "AAPL")
    msft_out = next(i for i in out.items if i.ticker == "MSFT")

    # AAPL had no edges in graph2 -> stripped back to base
    assert aapl_out.network is None
    assert aapl_out.score == aapl_out.base_score
    assert "network" not in aapl_out.components

    # MSFT has a forward edge in graph2 -> blended
    assert msft_out.network is not None
    assert "network" in msft_out.components


def test_blend_twice_does_not_duplicate_reasons():
    """Applying apply_network twice with the same graph must NOT duplicate network reasons."""
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    settings = Settings()
    once = apply_network(board, graph, settings)
    twice = apply_network(once, graph, settings)

    a1 = next(i for i in once.items if i.ticker == "AAPL")
    a2 = next(i for i in twice.items if i.ticker == "AAPL")

    # Score and net must be identical
    assert a1.score == a2.score
    assert a1.net == a2.net

    # Reasons list must be non-empty (guard against silent degeneration) and identical
    assert a1.reasons
    assert a1.reasons == a2.reasons


def _row(t, base_net=0.0, base_score=50.0):
    return StockScore(ticker=t, name=t, price=1, change_pct=0, score=base_score,
                      direction="hold", net=base_net, base_net=base_net, base_score=base_score)


def test_apply_network_uses_base_override_for_offboard_neighbour():
    # Board has only AAA; its partner ZZZ lives only in the override (the all-board fallback).
    board = ScreenBoard(scope="portfolio", items=[_row("AAA")])
    graph = KnowledgeGraph(nodes=["AAA", "ZZZ"], edges=[
        GraphEdge(source="AAA", target="ZZZ", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    override = {"ZZZ": _row("ZZZ", base_net=0.8)}
    blended = apply_network(board, graph, Settings(), base_override=override)
    aaa = blended.items[0]
    assert aaa.network is not None and aaa.network.signed > 0   # picked up ZZZ via override

    # Without the override the neighbour is unknown -> no state contribution.
    plain = apply_network(board, graph, Settings())
    assert plain.items[0].network is not None  # edge still scores the event term
    assert plain.items[0].network.signed <= aaa.network.signed
