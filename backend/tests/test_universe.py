import pytest

from app.data import universe
from app.data.universe import list_sectors, load_universe
from app.models.schemas import UniverseEntry


@pytest.fixture(autouse=True)
def _clear_universe_cache():
    # Tests monkeypatch _DATA_FILE; clear the lru_cache before and after each
    # test so cached entries never leak across tests.
    universe._all_entries.cache_clear()
    yield
    universe._all_entries.cache_clear()


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


SAMPLE_HTML = """
<table>
  <thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr></thead>
  <tbody>
    <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>Tech Hardware</td></tr>
    <tr><td>MSFT</td><td>Microsoft</td><td>Information Technology</td><td>Software</td></tr>
    <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector</td></tr>
  </tbody>
</table>
"""


def test_parse_sp500_extracts_and_normalizes_symbols():
    entries = universe.parse_sp500(SAMPLE_HTML)
    by = {e.ticker: e for e in entries}
    assert set(by) == {"AAPL", "MSFT", "BRK-B"}      # BRK.B -> BRK-B (yfinance form)
    assert by["AAPL"].sector == "Information Technology"
    assert by["BRK-B"].name == "Berkshire Hathaway"


def test_parse_sp500_dedupes_by_ticker():
    dup = SAMPLE_HTML.replace(
        "  </tbody>",
        "    <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>x</td></tr>\n  </tbody>",
    )
    entries = universe.parse_sp500(dup)
    assert sum(1 for e in entries if e.ticker == "AAPL") == 1


def test_parse_sp500_raises_when_table_missing():
    with pytest.raises(ValueError):
        universe.parse_sp500("<table><thead><tr><th>Foo</th></tr></thead><tbody><tr><td>bar</td></tr></tbody></table>")
