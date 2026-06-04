from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.config.cache import Cache
from app.models.schemas import TruthPost

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
_PULL_TTL_SECONDS = 30 * 60
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


def _fetch_archive(url: str) -> list[dict]:
    resp = httpx.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_recent_posts(
    lookback_hours: int, source_url: str = ARCHIVE_URL, *, now: datetime | None = None
) -> list[TruthPost]:
    now = now or datetime.now(timezone.utc)
    try:
        return filter_recent(parse_posts(_fetch_archive(source_url)), lookback_hours, now)
    except Exception:
        return []


def fetch_recent_posts_cached(
    lookback_hours: int,
    source_url: str,
    cache: Cache,
    *,
    ttl_seconds: int = _PULL_TTL_SECONDS,
    now: datetime | None = None,
) -> list[TruthPost]:
    key = f"truth_posts:{source_url}:{lookback_hours}"
    cached = cache.get(key)
    if cached is not None:
        return [TruthPost.model_validate(p) for p in json.loads(cached)]
    posts = fetch_recent_posts(lookback_hours, source_url, now=now)
    cache.set(key, json.dumps([p.model_dump() for p in posts]), ttl_seconds)
    return posts
