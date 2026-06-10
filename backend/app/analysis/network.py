"""Pure, deterministic propagation of relationship signal across the knowledge graph.

No LLM, no I/O. `compute_network_signal` blends each edge's news-event sentiment (judged for
the SOURCE company) with the neighbour's current technical condition; `apply_network` (next
task) folds the result into the board via a closed-form re-blend.
"""
from __future__ import annotations

from app.analysis.scoring import direction_for
from app.models.schemas import (
    GraphEdge, KnowledgeGraph, NetworkConfig, NetworkInfluence, NetworkSignal,
    ScreenBoard, Settings, StockScore,
)

_SENTIMENT = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _type_sign(rel_type: str) -> float:
    """Competitor is the only relationship where you move AGAINST the neighbour."""
    return -1.0 if rel_type == "competitor" else 1.0


def _direction_word(signed: float) -> str:
    return "bullish" if signed > 0 else "bearish" if signed < 0 else "neutral"


def incident_edges(ticker: str, edges: list[GraphEdge], symmetric: set[str]) -> list[GraphEdge]:
    """Edges that should score ``ticker``: forward (ticker is the source, any type) plus reverse
    (ticker is the target AND the relationship is a mutual type). A self-loop is counted once."""
    out: list[GraphEdge] = []
    for e in edges:
        if e.source == ticker:
            out.append(e)
        elif e.target == ticker and e.type in symmetric:
            out.append(e)
    return out


def compute_network_signal(
    ticker: str,
    edges: list[GraphEdge],
    base_index: dict[str, StockScore],
    cfg: NetworkConfig,
) -> NetworkSignal:
    influences: list[NetworkInfluence] = []
    signed_sum = 0.0
    intensity_sum = 0.0
    for e in edges:
        is_reverse = e.source != ticker            # ticker is the TARGET -> neighbour is the source
        neighbour_id = e.source if is_reverse else e.target
        nb = base_index.get(neighbour_id)
        nb_net = nb.base_net if nb else 0.0   # neighbour's PRE-network vote -> one hop, no feedback
        nb_dir = nb.direction if nb else "unknown"
        tsign = _type_sign(e.type)
        state = tsign * nb_net
        event = _SENTIMENT.get(e.sentiment, 0.0)
        # The edge's news sentiment was judged from the SOURCE side; on a reverse edge it lands on
        # the neighbour with the type sign (competitor inverts; partner/other keep).
        event_term = tsign * event if is_reverse else event
        w = e.weight * e.confidence
        e_signed = w * (cfg.alpha_event * event_term + cfg.beta_state * state)
        e_intensity = w * max(abs(event_term), abs(state))
        signed_sum += e_signed
        intensity_sum += e_intensity
        influences.append(NetworkInfluence(
            neighbour=neighbour_id,
            name=nb.name if nb else "",
            type=e.type,
            edge_sentiment=e.sentiment,
            neighbour_direction=nb_dir,
            signed=round(e_signed, 3),
            reason=f"{e.type} {neighbour_id} ({_direction_word(e_signed)})",
        ))
    influences.sort(key=lambda i: abs(i.signed), reverse=True)
    return NetworkSignal(
        ticker=ticker,
        intensity=round(_clamp(intensity_sum, 0.0, 1.0), 3),
        signed=round(_clamp(signed_sum, -1.0, 1.0), 3),
        influences=influences,
        reasons=[i.reason for i in influences[:3]],
    )


_DIRECTIONAL = ("extremes", "trend", "momentum")


def blend_network_into_score(s: StockScore, sig: NetworkSignal, settings: Settings) -> StockScore:
    """Fold a computed network signal into ONE row's score/direction. Closed-form re-blend from
    base_score/base_net (never the already-blended score/net) so it stays idempotent. Shared by
    apply_network (per row) and the single-ticker score path."""
    weights = settings.screener.weights
    w_base = sum(weights.values()) or 1.0
    w_dir = sum(weights.get(f, 0.0) for f in _DIRECTIONAL) or 1.0
    w_net = settings.network.weight
    final_score = (s.base_score * w_base + 100.0 * sig.intensity * w_net) / (w_base + w_net)
    final_net = _clamp((s.base_net * w_dir + sig.signed * w_net) / (w_dir + w_net), -1.0, 1.0)
    direction = direction_for(final_net)
    components = dict(s.components)
    components["network"] = round(sig.intensity, 2)
    return s.model_copy(update={
        "score": round(_clamp(final_score, 0.0, 100.0), 1),
        "net": round(final_net, 3),
        "direction": direction,
        "components": components,
        "reasons": sig.reasons + s.reasons,   # network reasons first
        "network": sig,
    })


def apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings) -> ScreenBoard:
    """Fold a capped `network` family into each focus company's score/direction.

    Pure: reads neighbours' BASE scores (one hop, no feedback) and returns a new board. Blends from
    each row's ``base_score``/``base_net`` (never the already-blended values) via
    ``blend_network_into_score``, so applying it twice is idempotent and never double-counts.
    """
    ncfg = settings.network
    if not ncfg.enabled or not graph.edges:
        return board

    base_index = {s.ticker: s for s in board.items}
    symmetric = set(ncfg.symmetric_types)

    new_items = []
    for s in board.items:
        edges = incident_edges(s.ticker, graph.edges, symmetric)
        if not edges:
            new_items.append(s)
            continue
        sig = compute_network_signal(s.ticker, edges, base_index, ncfg)
        new_items.append(blend_network_into_score(s, sig, settings))

    new_items.sort(key=lambda x: x.score, reverse=True)
    return board.model_copy(update={"items": new_items})
