from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.models.schemas import TruthPost

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def parse_posts(raw: list[dict]) -> list[TruthPost]:
    posts: list[TruthPost] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        posts.append(
            TruthPost(
                id=str(row.get("id", "")),
                created_at=str(row.get("created_at", "")),
                content=_strip_html(str(row.get("content", ""))),
                url=str(row.get("url", "")),
            )
        )
    return posts


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def filter_recent(posts: list[TruthPost], hours: int, now: datetime) -> list[TruthPost]:
    cutoff = now - timedelta(hours=hours)
    out = []
    for p in posts:
        dt = _parse_dt(p.created_at)
        if dt is not None and dt >= cutoff:
            out.append(p)
    return out
