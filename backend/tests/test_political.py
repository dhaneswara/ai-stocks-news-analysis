import json
from datetime import datetime, timezone

from app.analysis.political import build_mood_prompt, find_mentions, summarize_market_mood
from app.config.cache import Cache
from app.models.schemas import TruthPost


def _post(pid, content):
    return TruthPost(id=pid, created_at="2026-06-04T10:00:00Z", content=content, url=f"https://t/{pid}")


def test_finds_cashtag_company_and_bare_ticker():
    posts = [
        _post("1", "I love $AAPL and what they do"),
        _post("2", "Apple should build in America"),
        _post("3", "AAPL is great"),
        _post("4", "nothing relevant here"),
    ]
    hits = find_mentions(posts, "AAPL", "Apple Inc.")
    ids = {m.post_id for m in hits}
    assert ids == {"1", "2", "3"}


def test_word_boundary_blocks_substring_false_positive():
    # "Apple" must not match inside "applesauce"; bare lowercase "aapl" is not a cashtag/ticker
    posts = [_post("1", "I bought applesauce and aapl-flavored candy")]
    assert find_mentions(posts, "AAPL", "Apple Inc.") == []


def test_bare_ticker_is_case_sensitive_to_avoid_common_words():
    # ticker "ON" must not match the english word "on"
    posts = [_post("1", "we are working on it")]
    assert find_mentions(posts, "ON", "ON Semiconductor") == []


def test_excerpt_and_one_mention_per_post():
    posts = [_post("1", "$AAPL $AAPL twice")]
    hits = find_mentions(posts, "AAPL", "Apple Inc.")
    assert len(hits) == 1 and "AAPL" in hits[0].excerpt


MOOD_JSON = json.dumps({
    "lean": "risk_off",
    "confidence": 0.7,
    "summary": "Tariff threats dominate.",
    "themes": [{"label": "Tariffs on China", "lean": "bearish", "quote": "massive"}],
})


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def test_build_mood_prompt_includes_posts():
    system, user = build_mood_prompt([_post("1", "Tariffs on China")])
    assert "Tariffs on China" in user
    assert "JSON" in user


def test_summarize_returns_neutral_for_no_posts(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([], FakeProvider([MOOD_JSON]), "m", "fake", cache)
    assert mood.lean == "neutral" and mood.post_count == 0


def test_summarize_parses_llm_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([_post("1", "Tariffs")], FakeProvider([MOOD_JSON]), "m", "fake", cache)
    assert mood.lean == "risk_off"
    assert mood.themes[0].lean == "bearish"
    assert mood.post_count == 1


def test_summarize_is_cached_per_provider_day(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    provider = FakeProvider([MOOD_JSON])  # only ONE output available
    posts = [_post("1", "Tariffs")]
    a = summarize_market_mood(posts, provider, "m", "fake", cache)
    b = summarize_market_mood(posts, provider, "m", "fake", cache)  # must hit cache, not pop again
    assert a.lean == b.lean == "risk_off"
    assert provider.calls == 1


def test_summarize_falls_back_to_neutral_on_bad_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([_post("1", "x")], FakeProvider(["not json"]), "m", "fake", cache)
    assert mood.lean == "neutral"


def test_summarize_treats_corrupt_cache_as_miss(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    key = f"truth_mood:fake:m:{now.date().isoformat()}"
    cache.set(key, "{ corrupt", 3600)  # corrupt entry
    mood = summarize_market_mood([_post("1", "Tariffs")], FakeProvider([MOOD_JSON]), "m", "fake", cache, now=now)
    assert mood.lean == "risk_off"  # recomputed via the LLM, did not raise
