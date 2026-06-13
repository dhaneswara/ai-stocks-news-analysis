"""Static S&P 500 universe for the Discover screen.

`sp500.json` is a committed snapshot (ticker / name / GICS sector). It deliberately avoids any
network scrape on the request path. The list drifts (adds/drops) — refresh it manually (e.g.
quarterly) by replacing the file with a fresh constituent dump; no code change is needed. The
starter file ships a representative subset across all 11 sectors; appending the remaining names
only grows the data file.
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config.cache import Cache
from app.models.schemas import UniverseEntry
from app.services.stock_service import get_stock_data

_DATA_FILE = Path(__file__).with_name("sp500.json")
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_MIN_SP500_ROWS = 450  # module constant so tests can monkeypatch a smaller floor


@lru_cache
def _all_entries() -> tuple[UniverseEntry, ...]:
    raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return tuple(UniverseEntry(**row) for row in raw)


def load_universe(sector: str | None = None, cache: Cache | None = None) -> list[UniverseEntry]:
    entries = list(_all_entries())
    if cache is not None:
        seen = {e.ticker for e in entries}
        entries += [c for c in list_custom(cache) if c.ticker not in seen]
    if sector:
        return [e for e in entries if e.sector == sector]
    return entries


def list_sectors() -> list[str]:
    return sorted({e.sector for e in _all_entries()})


@lru_cache
def _sp500_tickers() -> frozenset[str]:
    return frozenset(e.ticker for e in _all_entries())


def is_sp500_member(ticker: str) -> bool:
    """True iff the ticker is in the committed S&P 500 list (never includes custom companies)."""
    return ticker.upper().strip() in _sp500_tickers()


_CUSTOM_KEY = "custom_universe"
_CUSTOM_TTL_SECONDS = 3650 * 24 * 60 * 60  # ~10 years (effectively permanent), like ontologies


def list_custom(cache: Cache) -> list[UniverseEntry]:
    raw = cache.get(_CUSTOM_KEY)
    if not raw:
        return []
    try:
        return [UniverseEntry(**row) for row in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def add_custom(entry: UniverseEntry, cache: Cache) -> UniverseEntry:
    """Persist a custom (non-S&P) company; idempotent on ticker (last write wins)."""
    rows = [c for c in list_custom(cache) if c.ticker != entry.ticker]
    rows.append(entry)
    cache.set(_CUSTOM_KEY, json.dumps([c.model_dump() for c in rows]), _CUSTOM_TTL_SECONDS)
    return entry


def delete_custom(ticker: str, cache: Cache) -> bool:
    t = ticker.upper().strip()
    rows = list_custom(cache)
    kept = [c for c in rows if c.ticker != t]
    if len(kept) == len(rows):
        return False
    cache.set(_CUSTOM_KEY, json.dumps([c.model_dump() for c in kept]), _CUSTOM_TTL_SECONDS)
    return True


def resolve_custom_entry(ticker: str, params, cache: Cache) -> tuple[UniverseEntry, float]:
    """Auto-fill a custom company from market data. Raises ValueError when the ticker has no
    price history (the caller maps that to HTTP 422). Uses a short window — enough to validate
    the ticker and read the current price."""
    t = ticker.upper().strip()
    stock = get_stock_data(t, "1mo", params, cache)  # validates; raises ValueError if unknown
    entry = UniverseEntry(ticker=t, name=stock.company_name, sector=stock.sector,
                          exchange=stock.exchange)
    return entry, stock.price.current


def _fetch_sp500_html(url: str = WIKI_SP500_URL) -> str:
    """Isolated network I/O (swappable in tests). Wikipedia 403s the default UA."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sp500-universe-refresh)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse_sp500(html: str) -> list[UniverseEntry]:
    """Parse the constituents table into UniverseEntry rows. Pure + deterministic."""
    tables = pd.read_html(io.StringIO(html))
    df = next(
        (t for t in tables if {"Symbol", "Security", "GICS Sector"}.issubset(set(map(str, t.columns)))),
        None,
    )
    if df is None:
        raise ValueError("S&P 500 constituents table not found in the page")
    seen: set[str] = set()
    out: list[UniverseEntry] = []
    for _, row in df.iterrows():
        ticker = str(row["Symbol"]).strip().replace(".", "-").upper()
        name = str(row["Security"]).strip()
        sector = str(row["GICS Sector"]).strip()
        if ticker and name and sector and ticker.lower() != "nan" and ticker not in seen:
            seen.add(ticker)
            out.append(UniverseEntry(ticker=ticker, name=name, sector=sector))
    return out


def _dump_entries(entries: list[UniverseEntry]) -> str:
    """Serialize in the committed one-object-per-line style (stable, diff-friendly)."""
    lines = ["["]
    for i, e in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        lines.append(
            f'  {{ "ticker": {json.dumps(e.ticker, ensure_ascii=False)}, '
            f'"name": {json.dumps(e.name, ensure_ascii=False)}, '
            f'"sector": {json.dumps(e.sector, ensure_ascii=False)} }}{comma}'
        )
    lines.append("]")
    return "\n".join(lines) + "\n"


def refresh_universe(url: str = WIKI_SP500_URL) -> dict:
    """Scrape the current S&P 500 list and rewrite the universe file atomically.

    Validates before writing and refuses (raises) on a short/garbage parse, so a bad
    scrape never clobbers the existing file. Clears the loader cache so the change takes
    effect without a server restart.
    """
    entries = parse_sp500(_fetch_sp500_html(url))
    has_anchor = any(e.ticker == "AAPL" and e.sector == "Information Technology" for e in entries)
    if len(entries) < _MIN_SP500_ROWS or not has_anchor:
        raise ValueError(
            f"refused to update universe: parsed {len(entries)} rows, anchor present={has_anchor}"
        )
    entries.sort(key=lambda e: (e.sector, e.ticker))

    tmp = _DATA_FILE.with_name(_DATA_FILE.name + ".tmp")
    tmp.write_text(_dump_entries(entries), encoding="utf-8")
    os.replace(tmp, _DATA_FILE)  # atomic swap
    _all_entries.cache_clear()
    _sp500_tickers.cache_clear()  # membership set is derived from _all_entries — refresh it too

    return {
        "count": len(entries),
        "sectors": dict(sorted(Counter(e.sector for e in entries).items())),
        "source": url,
    }
