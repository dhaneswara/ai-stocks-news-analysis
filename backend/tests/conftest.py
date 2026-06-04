import pytest

from app.data import truth_social


@pytest.fixture(autouse=True)
def _stub_truth_archive(monkeypatch):
    """Keep the whole suite hermetic: the Truth Social signal defaults ON, so any test that
    exercises ``run_analysis`` (directly or via ``/api/analyze``) would otherwise make a live
    HTTP call to the public archive. Stub the lowest-level fetch to return no posts by default;
    tests that specifically exercise fetching override ``_fetch_archive`` /
    ``fetch_recent_posts_cached`` themselves, which takes precedence over this autouse stub.
    With no posts, ``summarize_market_mood`` short-circuits to a neutral mood (no LLM call).
    """
    monkeypatch.setattr(truth_social, "_fetch_archive", lambda url: [])
