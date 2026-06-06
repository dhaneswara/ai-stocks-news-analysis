"""Pure, deterministic propagation of relationship signal across the knowledge graph.

No LLM, no I/O. `compute_network_signal` blends each edge's news-event sentiment (judged for
the SOURCE company) with the neighbour's current technical condition; `apply_network` (next
task) folds the result into the board via a closed-form re-blend.
"""
from __future__ import annotations

from app.models.schemas import GraphEdge, NetworkConfig, NetworkInfluence, NetworkSignal, StockScore

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
        nb_net = nb.net if nb else 0.0
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
