from app.analysis.relationships import TickerResolver
from app.models.schemas import GraphEdge, ImportReport, ImportSetSummary, KnowledgeGraph, NodeMeta, UniverseEntry
from app.network.import_model import map_relation_type, normalize_import

UNIVERSE = [
    UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
    UniverseEntry(ticker="NVDA", name="NVIDIA", sector="Tech"),
]


def _resolver():
    return TickerResolver(UNIVERSE)


def test_map_relation_type():
    assert map_relation_type("supplier") == "supplier"
    assert map_relation_type("invests_in") == "owner"
    assert map_relation_type("licenses") == "partner"
    assert map_relation_type("totally-unknown") == "other"
    assert map_relation_type(None) == "other"


def test_resolves_tickers_and_keeps_externals():
    payload = {
        "name": "x",
        "nodes": [
            {"id": "NVDA", "label": "NVIDIA", "kind": "company"},
            {"id": "OpenAI", "label": "OpenAI", "kind": "private_company"},
        ],
        "edges": [
            {"source": "NVDA", "target": "OpenAI", "type": "customer",
             "sentiment": "positive", "weight": 0.8, "confidence": 0.7},
        ],
    }
    graph, report = normalize_import(payload, _resolver())
    assert "NVDA" in graph.nodes                     # resolved to ticker
    assert "ext:openai" in graph.nodes               # external, namespaced
    assert graph.node_meta["ext:openai"].label == "OpenAI"
    assert graph.node_meta["ext:openai"].source == "imported"
    e = graph.edges[0]
    assert e.source == "NVDA" and e.target == "ext:openai"
    assert e.origin == "imported"
    assert report.nodes_added == 2 and report.edges_added == 1


def test_type_mapping_defaults_and_clamp():
    payload = {"edges": [
        {"source": "AAPL", "target": "NVDA", "type": "acquired",
         "sentiment": "??", "weight": 5, "confidence": -1},
    ]}
    graph, _ = normalize_import(payload, _resolver())
    e = graph.edges[0]
    assert e.type == "owner"            # acquired -> owner
    assert e.sentiment == "neutral"     # invalid -> neutral
    assert e.weight == 1.0 and e.confidence == 0.0   # clamped to 0..1


def test_drops_self_loops_and_dedupes():
    payload = {"edges": [
        {"source": "AAPL", "target": "AAPL", "type": "partner"},          # self-loop -> dropped
        {"source": "AAPL", "target": "NVDA", "type": "partner"},
        {"source": "AAPL", "target": "NVDA", "type": "partner"},          # dup -> dropped
    ]}
    graph, report = normalize_import(payload, _resolver())
    assert len(graph.edges) == 1
    assert report.dropped == 2


def test_non_dict_payload_is_safe():
    graph, report = normalize_import("not a dict", _resolver())
    assert graph.edges == [] and report.warnings


def test_new_schema_defaults():
    e = GraphEdge(source="AAPL", target="MSFT", type="other")
    assert e.origin == "extracted"          # back-compat default
    g = KnowledgeGraph()
    assert g.node_meta == {}                 # back-compat default
    m = NodeMeta(label="OpenAI", kind="private_company", source="imported")
    assert m.source == "imported"
    assert ImportSetSummary().edge_count == 0
    assert ImportReport().warnings == []


def test_node_meta_defaults():
    m = NodeMeta()
    assert m.label == "" and m.kind == "" and m.source == "native"


def test_graph_round_trips_with_other_type_and_meta():
    g = KnowledgeGraph(
        nodes=["AAPL", "ext:openai"],
        edges=[GraphEdge(source="AAPL", target="ext:openai", type="other", origin="imported")],
        node_meta={"ext:openai": NodeMeta(label="OpenAI", kind="private_company", source="imported")},
    )
    restored = KnowledgeGraph.model_validate_json(g.model_dump_json())
    assert restored.edges[0].type == "other"
    assert restored.edges[0].origin == "imported"
    assert restored.node_meta["ext:openai"].label == "OpenAI"
