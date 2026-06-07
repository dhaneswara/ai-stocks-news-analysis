from app.models.schemas import GraphEdge, NodeMeta


def test_manual_origin_and_source_are_valid():
    e = GraphEdge(source="AAPL", target="man:ai-demand", type="other", origin="manual")
    assert e.origin == "manual"
    m = NodeMeta(label="AI demand", kind="concept", source="manual")
    assert m.source == "manual"


def test_existing_defaults_unchanged():
    assert GraphEdge(source="A", target="B", type="supplier").origin == "extracted"
    assert NodeMeta().source == "native"
