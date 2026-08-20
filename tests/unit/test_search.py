from unittest import mock
import json

def test_normalize_dedupe_and_limit():
    from webx.searxng import normalize_results
    from webx.models import SearchQuery
    q = SearchQuery(query="test", limit=2, category="general")
    raw = {
        "results": [
            {"title": "A", "url": "https://example.com/", "content": "snippet A", "engines": ["duckduckgo"], "score": 1.0},
            {"title": "B", "url": "https://example.com", "content": "snippet B", "engines": ["google"]},  # duplicate
            {"title": "C", "url": "https://example.org/", "content": "snippet C", "score": 0.5},
        ]
    }
    resp = normalize_results(raw, q)
    # deduped: example.com appears once (first), plus example.org = 2 results due to limit 2
    assert len(resp.results) == 2
    assert resp.results[0].url == "https://example.com/"
    assert resp.results[0].title == "A"
    assert resp.results[1].url == "https://example.org/"
    assert resp.meta.result_count == 2

def test_normalize_missing_optional():
    from webx.searxng import normalize_results
    from webx.models import SearchQuery
    q = SearchQuery(query="x", limit=8)
    raw = {"results": [{"url": "https://example.com"}]}
    resp = normalize_results(raw, q)
    assert resp.results[0].title == ""
    assert resp.results[0].snippet == ""
    assert resp.results[0].engines == []
    assert resp.results[0].score == 0.0

def test_normalize_malformed():
    from webx.searxng import normalize_results
    from webx.models import SearchQuery
    from webx.errors import SearxngSearchError
    q = SearchQuery(query="x")
    try:
        normalize_results({"results": "notalist"}, q)
        assert False
    except SearxngSearchError:
        pass
    try:
        normalize_results("notdict", q)  # type: ignore
        assert False
    except SearxngSearchError:
        pass

def test_search_params_and_ensure_running(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx"))
    from webx.config import get_config
    from webx.searxng import SearxngClient
    cfg = get_config()
    # mock ensure_running
    with mock.patch("webx.searxng.ensure_running") as m_ensure:
        # mock httpx Client
        fake_json = {"results": [{"title": "T", "url": "https://example.com", "content": "s", "engines": ["a"], "score": 1}]}
        mock_resp = mock.Mock(status_code=200, headers={"content-type": "application/json"})
        mock_resp.json.return_value = fake_json
        mock_resp.text = json.dumps(fake_json)
        mock_client = mock.MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        with mock.patch("webx.searxng.httpx.Client", return_value=mock_client):
            c = SearxngClient(cfg)
            resp = c.search("hello world", limit=5, category="general", language="en", page=2, time_range="month", safe_search=1, engines=["google","bing"])
            m_ensure.assert_called_once_with(cfg)
            # verify params sent
            args, kwargs = mock_client.get.call_args
            url = args[0]
            assert url == cfg.searxng_url.rstrip("/") + "/search"
            params = kwargs["params"]
            assert params["q"] == "hello world"
            assert params["format"] == "json"
            assert params["categories"] == "general"
            assert params["language"] == "en"
            assert params["pageno"] == "2"
            assert params["time_range"] == "month"
            assert params["safesearch"] == "1"
            assert params["engines"] == "google,bing"
            assert len(resp.results) == 1
            assert resp.query == "hello world"

def test_search_cli_json_not_contaminated(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-cli"))
    from webx.config import get_config
    from webx.core import WebX
    from webx import searxng as searxng_mod
    cfg = get_config()
    # mock ensure_running and request
    fake = {"results": [{"title": "Title", "url": "https://example.com", "content": "snippet"}]}
    mock_resp = mock.Mock(status_code=200, headers={"content-type": "application/json"})
    mock_resp.json.return_value = fake
    mock_resp.text = json.dumps(fake)
    mock_client = mock.MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    # ensure init
    from webx.lifecycle import init_runtime
    init_runtime(cfg)
    with mock.patch("webx.searxng.ensure_running", return_value=None):
        with mock.patch("webx.searxng.httpx.Client", return_value=mock_client):
            # call CLI search via main
            from webx.cli import main
            import io, contextlib, sys
            # capture stdout/stderr via main's prints; we mock to use subprocess style
            # use capsys via direct call but main prints to stdout
            # We'll run main and check stdout via capsys
            ret = main(["search", "hello", "--limit", "5"])
            assert ret == 0
            out, err = capsys.readouterr()
            # stdout should be valid JSON
            data = json.loads(out.strip())
            assert data["query"] == "hello"
            assert "results" in data
            # stderr should not contain JSON results
            assert "snippet" not in err

def test_search_invalid_time_range(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-err"))
    from webx.config import get_config
    from webx.searxng import SearxngClient
    from webx.errors import SearxngSearchError
    cfg = get_config()
    with mock.patch("webx.searxng.ensure_running"):
        c = SearxngClient(cfg)
        try:
            c.search("q", time_range="invalid")
            assert False
        except SearxngSearchError:
            pass
