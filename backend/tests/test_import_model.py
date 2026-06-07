from app.models.schemas import GraphEdge, ImportReport, ImportSetSummary, KnowledgeGraph, NodeMeta


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
