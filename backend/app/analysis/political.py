from __future__ import annotations

import re
from datetime import datetime, timezone

from app.analysis.analyzer import extract_json
from app.config.cache import Cache
from app.llm.base import LLMProvider
from app.models.schemas import MarketMood, Mention, MoodTheme, TruthPost

_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group)\b\.?", re.I
)


def _clean_company(name: str) -> str:
    return _SUFFIX_RE.sub("", name or "").strip(" ,.")


def _match_terms(ticker: str, company_name: str, aliases: list[str] | None):
    """(term, regex_flags) pairs. Cashtag + company + aliases are case-insensitive;
    the bare ticker is case-SENSITIVE so a ticker like 'ON' won't match the word 'on'."""
    terms: list[tuple[str, int]] = [(f"${ticker}", re.I), (ticker, 0)]
    name = _clean_company(company_name)
    if name:
        terms.append((name, re.I))
    for a in aliases or []:
        if a:
            terms.append((a, re.I))
    # Longest term first so '$AAPL' wins over 'AAPL' for the `matched` label.
    return sorted(terms, key=lambda t: len(t[0]), reverse=True)


def find_mentions(
    posts: list[TruthPost], ticker: str, company_name: str, aliases: list[str] | None = None
) -> list[Mention]:
    compiled = [
        (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags))
        for term, flags in _match_terms(ticker, company_name, aliases)
    ]
    out: list[Mention] = []
    for p in posts:
        for term, pattern in compiled:
            m = pattern.search(p.content)
            if m:
                start, end = max(0, m.start() - 40), min(len(p.content), m.end() + 40)
                out.append(
                    Mention(
                        post_id=p.id,
                        created_at=p.created_at,
                        matched=term,
                        excerpt=p.content[start:end].strip(),
                        url=p.url,
                    )
                )
                break  # one mention per post
    return out


_MOOD_TTL_SECONDS = 24 * 60 * 60

_MOOD_SYSTEM = (
    "You read recent social-media posts from a market-moving political figure and summarize "
    "their likely SHORT-TERM effect on US equities. Judge intent and target, not keywords: "
    "announcing a deal, tariff pause, or rate-cut pressure leans bullish; threatening tariffs, "
    "sanctions, or war leans bearish; praising a company is bullish for it, attacking one is "
    "bearish for it. Respond with ONLY a single JSON object, no prose, no code fences."
)

_MOOD_SCHEMA_HINT = """Return JSON with exactly these fields:
{
  "lean": "risk_on" | "neutral" | "risk_off",
  "confidence": number between 0 and 1,
  "summary": string (1-2 sentences on the NET market read),
  "themes": [ { "label": string, "lean": "bullish"|"bearish"|"neutral", "quote": string } ]
}
Base "lean" on the NET effect across all posts. Give 0-4 themes, each citing a concrete driver
(tariffs, Fed, war/ceasefire, a named company) with a short verbatim quote. If the posts carry no
clear market relevance, return lean "neutral", low confidence, and an empty themes list."""


def build_mood_prompt(posts: list[TruthPost]) -> tuple[str, str]:
    lines = "\n".join(f"- [{p.created_at}] {p.content[:280]}" for p in posts[:40])
    user = f"Recent posts:\n{lines or '- (none)'}\n\n{_MOOD_SCHEMA_HINT}"
    return _MOOD_SYSTEM, user


def _neutral_mood(post_count: int, as_of: str) -> MarketMood:
    return MarketMood(lean="neutral", confidence=0.0, summary="", themes=[],
                      as_of=as_of, post_count=post_count)


def summarize_market_mood(
    posts: list[TruthPost],
    provider: LLMProvider,
    model: str,
    provider_name: str,
    cache: Cache,
    *,
    now: datetime | None = None,
) -> MarketMood:
    now = now or datetime.now(timezone.utc)
    as_of = now.isoformat()
    if not posts:
        return _neutral_mood(0, as_of)

    key = f"truth_mood:{provider_name}:{model}:{now.date().isoformat()}"
    cached = cache.get(key)
    if cached is not None:
        try:
            return MarketMood.model_validate_json(cached)
        except Exception:
            pass  # corrupt/stale cache entry -> recompute below

    system, user = build_mood_prompt(posts)
    try:
        payload = extract_json(provider.complete(system, user))
        themes = [MoodTheme(**t) for t in payload.get("themes", []) if isinstance(t, dict)]
        mood = MarketMood(
            lean=payload.get("lean", "neutral"),
            confidence=float(payload.get("confidence", 0.0)),
            summary=str(payload.get("summary", "")),
            themes=themes,
            as_of=as_of,
            post_count=len(posts),
        )
    except Exception:
        mood = _neutral_mood(len(posts), as_of)

    cache.set(key, mood.model_dump_json(), _MOOD_TTL_SECONDS)
    return mood
