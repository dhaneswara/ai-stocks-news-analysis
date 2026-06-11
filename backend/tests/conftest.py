import os
import tempfile

# Sandbox DATA_DIR before any app module is imported: app.deps resolves DATA_DIR at
# import time and its @lru_cache store singletons otherwise point at the developer's
# real backend/data/app.db. Any test that exercises a route without overriding every
# store dependency would silently write there (an /api/analyze test once recorded a
# synthetic AAPL prediction that the Evaluation page then displayed as a real call).
_SANDBOX_DATA_DIR = tempfile.TemporaryDirectory(
    prefix="stocks-test-data-", ignore_cleanup_errors=True
)
os.environ["DATA_DIR"] = _SANDBOX_DATA_DIR.name

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
