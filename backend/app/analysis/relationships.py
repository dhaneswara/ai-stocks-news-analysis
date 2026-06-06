"""AI extraction of inter-company relationship edges from a company's news headlines.

Mirrors `political.py`: one cached LLM call per company per day, parse with `extract_json`,
degrade silently to an empty edge list on any failure. `TickerResolver` grounds every edge
target in the universe (closed vocabulary) so the model cannot invent nodes.
"""
from __future__ import annotations

import re

from app.models.schemas import UniverseEntry

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
