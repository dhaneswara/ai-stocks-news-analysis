from __future__ import annotations

import re

from app.models.schemas import Mention, TruthPost

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
