import pytest

from app.data import universe
from app.data.universe import is_sp500_member, list_sectors, load_universe
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


def test_is_sp500_member_checks_committed_list():
    assert is_sp500_member("AAPL") is True
    assert is_sp500_member("aapl ") is True      # normalized
    assert is_sp500_member("NOTREAL") is False


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


def test_refresh_universe_writes_and_clears_cache(tmp_path, monkeypatch):
    out = tmp_path / "sp500.json"
    monkeypatch.setattr(universe, "_DATA_FILE", out)
    monkeypatch.setattr(universe, "_MIN_SP500_ROWS", 2)
    monkeypatch.setattr(universe, "_fetch_sp500_html", lambda url=universe.WIKI_SP500_URL: SAMPLE_HTML)

    summary = universe.refresh_universe()
    assert summary["count"] == 3
    assert summary["sectors"]["Information Technology"] == 2
    assert out.exists()
    # cache was cleared -> the loader now reflects the freshly written file
    tickers = {e.ticker for e in universe.load_universe()}
    assert {"AAPL", "MSFT", "BRK-B"} <= tickers


def test_refresh_universe_refuses_bad_parse_and_keeps_existing_file(tmp_path, monkeypatch):
    out = tmp_path / "sp500.json"
    out.write_text('[\n  { "ticker": "ZZZ", "name": "Sentinel", "sector": "Energy" }\n]\n', encoding="utf-8")
    monkeypatch.setattr(universe, "_DATA_FILE", out)
    # default _MIN_SP500_ROWS (450) > the 3 parsed rows -> must refuse
    monkeypatch.setattr(universe, "_fetch_sp500_html", lambda url=universe.WIKI_SP500_URL: SAMPLE_HTML)

    with pytest.raises(ValueError):
        universe.refresh_universe()
    assert "Sentinel" in out.read_text(encoding="utf-8")  # untouched, no partial write


def test_custom_store_round_trip_and_merge(tmp_path):
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import UniverseEntry
    cache = Cache(str(tmp_path / "c.db"))

    assert universe.list_custom(cache) == []
    e = UniverseEntry(ticker="PRIV", name="Private Co", sector="Tech", exchange="NYSE")
    universe.add_custom(e, cache)
    assert [c.ticker for c in universe.list_custom(cache)] == ["PRIV"]

    merged = {x.ticker for x in universe.load_universe(cache=cache)}
    assert "PRIV" in merged and "AAPL" in merged       # custom appended to committed S&P
    assert universe.is_sp500_member("PRIV") is False    # committed-only membership

    assert universe.delete_custom("PRIV", cache) is True
    assert universe.list_custom(cache) == []


def test_resolve_custom_entry_autofetches(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import IndicatorParams, PriceSummary, StockData
    cache = Cache(str(tmp_path / "c.db"))

    def fake_stock(ticker, period, params, cache):
        return StockData(ticker=ticker, company_name="Private Co", as_of="t",
                         exchange="NYSE", sector="Tech",
                         price=PriceSummary(current=42.5, change=0, change_pct=0),
                         candles=[], fundamentals={}, indicators={})

    monkeypatch.setattr(universe, "get_stock_data", fake_stock)
    entry, price = universe.resolve_custom_entry("priv ", IndicatorParams(), cache)
    assert entry.ticker == "PRIV" and entry.name == "Private Co"
    assert entry.sector == "Tech" and entry.exchange == "NYSE" and price == 42.5


def test_resolve_custom_entry_rejects_unknown(tmp_path, monkeypatch):
    import pytest
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import IndicatorParams
    monkeypatch.setattr(universe, "get_stock_data",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("No price history")))
    with pytest.raises(ValueError):
        universe.resolve_custom_entry("NOPE", IndicatorParams(), Cache(str(tmp_path / "c.db")))
