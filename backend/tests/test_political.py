from app.analysis.political import find_mentions
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
