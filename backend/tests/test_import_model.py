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
