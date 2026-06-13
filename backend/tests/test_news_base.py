from app.news.base import NewsError, host_of


def test_host_of_strips_www():
    assert host_of("https://www.reuters.com/path") == "reuters.com"
    assert host_of("https://finance.yahoo.com/x") == "finance.yahoo.com"
    assert host_of("not a url") == ""


def test_news_error_is_exception():
    assert issubclass(NewsError, Exception)
