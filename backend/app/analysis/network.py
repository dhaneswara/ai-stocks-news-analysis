"""Pure, deterministic propagation of relationship signal across the knowledge graph.

No LLM, no I/O. `compute_network_signal` blends each edge's news-event sentiment (judged for
the SOURCE company) with the neighbour's current technical condition; `apply_network` (next
task) folds the result into the board via a closed-form re-blend.
"""
from __future__ import annotations

from collections import defaultdict

from app.analysis.scoring import _DIRECTION_THRESHOLD
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
        nb = base_index.get(e.target)
        nb_net = nb.base_net if nb else 0.0   # neighbour's PRE-network vote -> one hop, no feedback
        nb_dir = nb.direction if nb else "unknown"
        state = _type_sign(e.type) * nb_net
        event = _SENTIMENT.get(e.sentiment, 0.0)
        w = e.weight * e.confidence
        e_signed = w * (cfg.alpha_event * event + cfg.beta_state * state)
        e_intensity = w * max(abs(event), abs(state))
        signed_sum += e_signed
        intensity_sum += e_intensity
        influences.append(NetworkInfluence(
            neighbour=e.target,
            name=nb.name if nb else "",
            type=e.type,
            edge_sentiment=e.sentiment,
            neighbour_direction=nb_dir,
            signed=round(e_signed, 3),
            reason=f"{e.type} {e.target} ({_direction_word(e_signed)})",
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


def apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings) -> ScreenBoard:
    """Fold a capped `network` family into each focus company's score/direction.

    Pure: reads neighbours' BASE scores (one hop, no feedback) and returns a new board.
    Re-blend is the closed form of adding one weighted family to `score_stock`'s own formula.
    It blends from each row's ``base_score``/``base_net`` (never the already-blended ``score``/
    ``net``), so applying it twice — e.g. a sector rescan that merges previously-blended rows —
    yields the same result and never double-counts or feeds blended values back in.
    """
    ncfg = settings.network
    if not ncfg.enabled or not graph.edges:
        return board

    weights = settings.screener.weights
    w_base = sum(weights.values()) or 1.0
    w_dir = sum(weights.get(f, 0.0) for f in _DIRECTIONAL) or 1.0
    w_net = ncfg.weight

    base_index = {s.ticker: s for s in board.items}
    edges_by_source: dict[str, list[GraphEdge]] = defaultdict(list)
    for e in graph.edges:
        edges_by_source[e.source].append(e)

    new_items = []
    for s in board.items:
        edges = edges_by_source.get(s.ticker)
        if not edges:
            new_items.append(s)
            continue
        sig = compute_network_signal(s.ticker, edges, base_index, ncfg)
        final_score = (s.base_score * w_base + 100.0 * sig.intensity * w_net) / (w_base + w_net)
        final_net = _clamp((s.base_net * w_dir + sig.signed * w_net) / (w_dir + w_net), -1.0, 1.0)
        direction = (
            "buy" if final_net > _DIRECTION_THRESHOLD
            else "sell" if final_net < -_DIRECTION_THRESHOLD
            else "hold"
        )
        components = dict(s.components)
        components["network"] = round(sig.intensity, 2)
        new_items.append(s.model_copy(update={
            "score": round(_clamp(final_score, 0.0, 100.0), 1),
            "net": round(final_net, 3),
            "direction": direction,
            "components": components,
            "reasons": sig.reasons + s.reasons,   # network reasons first
            "network": sig,
        }))

    new_items.sort(key=lambda x: x.score, reverse=True)
    return board.model_copy(update={"items": new_items})
