"""AI extraction of inter-company relationship edges from a company's news headlines.

Mirrors `political.py`: one cached LLM call per company per day, parse with `extract_json`,
degrade silently to an empty edge list on any failure. `TickerResolver` grounds every edge
target in the universe (closed vocabulary) so the model cannot invent nodes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from app.analysis.analyzer import extract_json
from app.config.cache import Cache
from app.llm.base import LLMProvider
from app.models.schemas import GraphEdge, NetworkConfig, NewsItem, UniverseEntry

_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group|the|class [abc])\b\.?",
    re.I,
)


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _SUFFIX_RE.sub("", (name or "").lower())).strip()


class TickerResolver:
    """Resolve an LLM-named company to a canonical universe ticker, else None."""

    def __init__(self, entries: list[UniverseEntry]) -> None:
        self._by_ticker = {e.ticker.upper(): e.ticker for e in entries}
        self._by_name = {_normalize(e.name): e.ticker for e in entries}

    def resolve(self, name: str, ticker_hint: str | None) -> str | None:
        if ticker_hint and ticker_hint.upper() in self._by_ticker:
            return self._by_ticker[ticker_hint.upper()]
        norm = _normalize(name)
        return self._by_name.get(norm) if norm else None


_RELATION_TYPES: set[str] = {"supplier", "customer", "partner", "competitor", "owner", "subsidiary"}

_REL_TTL_SECONDS = 24 * 60 * 60

_SYSTEM = (
    "You extract business relationships between public companies from news headlines about ONE "
    "company (the SOURCE). For each relationship, classify its type and judge the news event's "
    "likely effect ON THE SOURCE company. Respond with ONLY a single JSON object, no prose, no "
    "code fences."
)


def _schema_hint(ticker: str) -> str:
    return f"""Return JSON with exactly this shape:
{{"edges":[{{"target_name": string, "target_ticker": string|null, "type": string,
            "sentiment": "positive"|"negative"|"neutral", "weight": number 0..1,
            "confidence": number 0..1, "evidence": string}}]}}
- "type" = the TARGET's role relative to {ticker}: supplier|customer|partner|competitor|owner|subsidiary.
- "sentiment" = the event's likely effect on {ticker} (positive = good for {ticker}).
- Include only relationships actually supported by the headlines; "evidence" = a short quote.
- Return an empty list if none."""


def build_extract_prompt(stock) -> tuple[str, str]:
    headlines = "\n".join(
        f"- [{n.published_at}] {n.title} ({n.source})" for n in stock.news[:10]
    ) or "- (none)"
    user = f"{stock.company_name} ({stock.ticker}). Recent headlines:\n{headlines}\n\n{_schema_hint(stock.ticker)}"
    return _SYSTEM, user


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _citation_url(evidence: str, news: list[NewsItem]) -> str:
    ev = (evidence or "").lower()
    for n in news:
        title = (n.title or "").lower()
        if title and any(len(w) > 4 and w in ev for w in title.split()):
            return n.url
    return ""


def extract_relationships(
    stock,
    resolver: TickerResolver,
    provider: LLMProvider,
    model: str,
    provider_name: str,
    cache: Cache,
    cfg: NetworkConfig,
    *,
    now: datetime | None = None,
    refresh: bool = False,
) -> list[GraphEdge]:
    now = now or datetime.now(timezone.utc)
    if not stock.news:
        return []

    key = f"relationships:{provider_name}:{model}:{stock.ticker}:{now.date().isoformat()}"
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            try:
                return [GraphEdge(**e) for e in json.loads(cached)]
            except Exception:
                pass  # corrupt entry -> recompute

    system, user = build_extract_prompt(stock)
    edges: list[GraphEdge] = []
    try:
        payload = extract_json(provider.complete(system, user))
        raw = payload.get("edges", []) if isinstance(payload, dict) else []
        for item in raw:
            if not isinstance(item, dict):
                continue
            target = resolver.resolve(item.get("target_name", ""), item.get("target_ticker"))
            if not target or target == stock.ticker:
                continue
            rel_type = item.get("type")
            if rel_type not in _RELATION_TYPES:
                continue
            try:
                conf = float(item.get("confidence", 0.0))
                weight = float(item.get("weight", 0.5))
            except (TypeError, ValueError):
                continue
            if conf < cfg.min_confidence:
                continue
            sentiment = item.get("sentiment", "neutral")
            if sentiment not in ("positive", "negative", "neutral"):
                sentiment = "neutral"
            evidence = str(item.get("evidence", ""))[:200]
            edges.append(GraphEdge(
                source=stock.ticker, target=target, type=rel_type, sentiment=sentiment,
                weight=_clamp01(weight), confidence=_clamp01(conf), evidence=evidence,
                url=_citation_url(evidence, stock.news), as_of=now.isoformat(),
            ))
    except Exception:
        return []  # degrade silently

    edges.sort(key=lambda e: e.weight * e.confidence, reverse=True)
    edges = edges[: cfg.max_edges_per_company]
    cache.set(key, json.dumps([e.model_dump() for e in edges]), _REL_TTL_SECONDS)
    return edges
