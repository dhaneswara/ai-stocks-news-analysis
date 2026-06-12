import pytest

from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, OntologyVersion
from app.network.store import (
    active_graph, delete_ontology, get_active_ontology, list_ontologies, load_ontology,
    save_ontology, set_active_ontology,
)


def _cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def _version(name="My Map", n=1):
    g = KnowledgeGraph(scope="explore", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)] * n)
    return OntologyVersion(name=name, saved_at=f"t{n}", expanded=["AAPL"], graph=g)


def test_save_and_load_roundtrip(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version(), cache)
    found = load_ontology("My Map", cache)
    assert found is not None and found.graph.nodes == ["AAPL", "TSM"]
    assert load_ontology("nope", cache) is None


def test_names_are_case_insensitively_unique(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("Tech"), cache)
    save_ontology(_version("tech", n=2), cache)        # updates "Tech", not a new entry
    names = [o.name for o in list_ontologies(cache)]
    assert names == ["Tech"]
    assert len(load_ontology("TECH", cache).graph.edges) == 2  # latest version (n=2 → 2 edges)
    assert len(list_ontologies(cache)[0].versions) == 2


def test_version_history_capped_at_five(tmp_path):
    cache = _cache(tmp_path)
    for i in range(7):
        save_ontology(_version(n=i), cache)
    assert len(list_ontologies(cache)[0].versions) == 5


def test_list_carries_counts_and_active_flag(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    save_ontology(_version("B"), cache)
    set_active_ontology("b", cache)                    # case-insensitive activate
    by_name = {o.name: o for o in list_ontologies(cache)}
    assert by_name["A"].active is False and by_name["B"].active is True
    assert by_name["A"].node_count == 2 and by_name["A"].edge_count == 1
    assert get_active_ontology(cache) == "B"


def test_activate_unknown_name_is_refused(tmp_path):
    cache = _cache(tmp_path)
    assert set_active_ontology("ghost", cache) is False
    assert get_active_ontology(cache) is None


def test_delete_clears_active_pointer(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    set_active_ontology("A", cache)
    assert delete_ontology("A", cache) is True
    assert get_active_ontology(cache) is None
    assert list_ontologies(cache) == []


def test_delete_single_version_keeps_pointer(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A", n=1), cache)
    save_ontology(_version("A", n=2), cache)
    set_active_ontology("A", cache)
    assert delete_ontology("A", cache, version="t1") is True
    assert get_active_ontology(cache) == "A"
    assert list_ontologies(cache)[0].versions == ["t2"]


def test_active_graph_empty_when_none_active(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)                # saved but NOT active
    g = active_graph(cache)
    assert g.nodes == [] and g.edges == []


def test_active_graph_returns_latest_active_revision(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A", n=1), cache)
    set_active_ontology("A", cache)
    save_ontology(_version("A", n=2), cache)           # newer revision of the active name
    assert len(active_graph(cache).edges) == 2 and active_graph(cache).nodes == ["AAPL", "TSM"]


def test_set_active_none_clears(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    set_active_ontology("A", cache)
    assert set_active_ontology(None, cache) is True
    assert get_active_ontology(cache) is None


def test_save_blank_name_is_refused(tmp_path):
    cache = _cache(tmp_path)
    with pytest.raises(ValueError):
        save_ontology(_version("   "), cache)
    assert list_ontologies(cache) == []
