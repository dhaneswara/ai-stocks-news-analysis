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

from app.models.schemas import UniverseEntry

_DATA_FILE = Path(__file__).with_name("sp500.json")
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_MIN_SP500_ROWS = 450  # module constant so tests can monkeypatch a smaller floor


@lru_cache
def _all_entries() -> tuple[UniverseEntry, ...]:
    raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return tuple(UniverseEntry(**row) for row in raw)


def load_universe(sector: str | None = None) -> list[UniverseEntry]:
    entries = _all_entries()
    if sector:
        return [e for e in entries if e.sector == sector]
    return list(entries)


def list_sectors() -> list[str]:
    return sorted({e.sector for e in _all_entries()})


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
