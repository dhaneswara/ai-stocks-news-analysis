"""Static S&P 500 universe for the Discover screen.

`sp500.json` is a committed snapshot (ticker / name / GICS sector). It deliberately avoids any
network scrape on the request path. The list drifts (adds/drops) — refresh it manually (e.g.
quarterly) by replacing the file with a fresh constituent dump; no code change is needed. The
starter file ships a representative subset across all 11 sectors; appending the remaining names
only grows the data file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models.schemas import UniverseEntry

_DATA_FILE = Path(__file__).with_name("sp500.json")


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
