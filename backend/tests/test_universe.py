from app.data.universe import list_sectors, load_universe
from app.models.schemas import UniverseEntry


def test_load_universe_returns_entries():
    u = load_universe()
    assert len(u) >= 20
    assert all(isinstance(e, UniverseEntry) for e in u)
    aapl = next(e for e in u if e.ticker == "AAPL")
    assert aapl.sector == "Information Technology"


def test_load_universe_filters_by_sector():
    energy = load_universe("Energy")
    assert energy and all(e.sector == "Energy" for e in energy)


def test_list_sectors_distinct_sorted():
    sectors = list_sectors()
    assert sectors == sorted(set(sectors))
    assert "Information Technology" in sectors
