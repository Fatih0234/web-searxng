import pathlib
import socket
from unittest import mock
import pytest

from webx.config import WebXConfig
from webx.errors import FetchError, UnsupportedContentTypeError, UnsafeUrlError, ExtractionError


@pytest.fixture(autouse=True)
def clear_reader_cache():
    from webx import reader as _reader_mod

    _reader_mod._READ_CACHE.clear()
    yield
    _reader_mod._READ_CACHE.clear()

# Tests use mocked http://example.com — live httpbin.org is flaky (503 from some nets, verified 2026-08-20) — see README for stable alternatives.

def make_cfg(**overrides):
    base = dict(
        runtime_dir=pathlib.Path("/tmp/webx-reader"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10*1024*1024,
        max_read_chars=40000,
        mcp_stop_on_exit=True,
    )
    base.update(overrides)
    return WebXConfig(**base)

def fake_public_getaddrinfo(host, *a, **kw):
    # always return public IP for any host not literal
    # For literal IP hosts, socket.getaddrinfo will be called with that IP string
    # We need to handle that: if host is IP literal, return that IP
    try:
        import ipaddress
        ip = ipaddress.ip_address(host.strip("[]"))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (str(ip), 0))]
    except Exception:
        pass
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]

def test_html_extraction(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    html = b"<html><head><title>Test</title></head><body><article><p>Hello <b>world</b> this is content.</p><p>More text.</p></article></body></html>"
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html", "content-length": str(len(html))}
    mock_resp.iter_bytes.return_value = [html]
    mock_stream = mock.MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    resp = reader.read("http://example.com")
    assert "Hello" in resp.content
    assert resp.truncated is False
    assert resp.final_url == "http://example.com"

def test_plain_text_passthrough(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    text = b"Just plain text\nLine 2"
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/plain", "content-length": str(len(text))}
    mock_resp.iter_bytes.return_value = [text]
    mock_stream = mock.MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    resp = reader.read("http://example.com/readme.txt")
    assert "Just plain text" in resp.content
    assert resp.content_type == "text/plain"

def test_unsupported_content_type(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/png", "content-length": "100"}
    mock_resp.iter_bytes.return_value = [b"\x89PNG"]
    mock_stream = mock.MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    with pytest.raises(UnsupportedContentTypeError):
        reader.read("http://example.com/image.png")

def test_oversized_content_length(monkeypatch):
    cfg = make_cfg(max_response_bytes=100)
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html", "content-length": "1000"}
    # iter_bytes shouldn't be called because pre-check fails
    mock_stream = mock.MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    with pytest.raises(FetchError, match="Content-Length"):
        reader.read("http://example.com/big.html")

def test_streamed_body_exceeds(monkeypatch):
    cfg = make_cfg(max_response_bytes=10)
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}  # no CL
    # chunks exceed limit
    mock_resp.iter_bytes.return_value = [b"12345", b"67890", b"abc"]
    mock_stream = mock.MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    with pytest.raises(FetchError, match="exceeds limit"):
        reader.read("http://example.com/stream.html")

def test_redirect_cap(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    # Each request returns redirect to next URL
    def make_redirect_resp(location):
        m = mock.MagicMock()
        m.status_code = 302
        m.headers = {"location": location}
        return m
    # We'll simulate 6 redirects -> should fail on 6th
    call_count = {"n": 0}
    def fake_client(*a, **kw):
        mock_c = mock.MagicMock()
        def fake_stream(method, url, headers=None):
            ms = mock.MagicMock()
            # For first 6 calls, return redirect; after that not reached
            ms.__enter__.return_value = make_redirect_resp(f"http://example.com/redirect{call_count['n']+1}")
            ms.__exit__.return_value = False
            call_count["n"] += 1
            return ms
        mock_c.stream.side_effect = fake_stream
        mock_c.__enter__.return_value = mock_c
        mock_c.__exit__.return_value = False
        return mock_c
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client)
    reader = WebReader(cfg)
    with pytest.raises(FetchError, match="Too many redirects"):
        reader.read("http://example.com/start")

def test_redirect_to_private_denied(monkeypatch):
    cfg = make_cfg()
    # First URL resolves public, second resolves private
    def fake_getaddrinfo(host, *a, **kw):
        if host == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]
        if host == "192.168.1.1":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14",0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    from webx.reader import WebReader
    mock_redirect = mock.MagicMock()
    mock_redirect.status_code = 302
    mock_redirect.headers = {"location": "http://192.168.1.1/secret"}
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_redirect
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    with pytest.raises(UnsafeUrlError):
        reader.read("http://example.com")

def test_truncation(monkeypatch):
    cfg = make_cfg(max_read_chars=1200)
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    # Create html that extracts to long text
    long_text = "word " * 500  # 2500 chars
    # Mock trafilatura to return long_text directly to avoid html parsing variance
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **kw: long_text)
    html = b"<html><body><p>" + long_text.encode()[:200] + b"</p></body></html>"
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.iter_bytes.return_value = [html]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    resp = reader.read("http://example.com/long", max_chars=1200)
    assert resp.truncated is True
    assert len(resp.content) <= 1200
    assert resp.characters == len(resp.content)

def test_extraction_fallback(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader
    html = b"<html><body><div>nav</div><p>Real content here with enough text to be considered valid.</p></body></html>"
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.iter_bytes.return_value = [html]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    # Mock extract to return None/empty, fallback returns something
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **kw: None)
    monkeypatch.setattr(trafilatura, "html2txt", lambda *a, **kw: "Fallback text content")
    monkeypatch.setattr("trafilatura.extract_metadata", lambda *a, **kw: None, raising=False)
    # Need to handle import inside reader: from trafilatura import extract_metadata may be dynamic
    reader = WebReader(cfg)
    resp = reader.read("http://example.com/fallback.html")
    assert "Fallback" in resp.content
    assert resp.engine == "trafilatura-fallback"


def test_json_raw_not_trafilatura(monkeypatch):
    """application/json must be returned raw (engine=raw) not via trafilatura, with charset honored."""
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader

    # utf-8 json
    body_utf8 = '{"key": "café", "num": 42}'.encode("utf-8")
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json; charset=utf-8"}
    mock_resp.iter_bytes.return_value = [body_utf8]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    reader = WebReader(cfg)
    resp = reader.read("http://example.com/data.json")
    assert resp.content == '{"key": "café", "num": 42}'
    assert resp.engine == "raw"
    assert resp.content_type == "application/json"
    assert resp.truncated is False

    # iso-8859-1 json (charset honoring)
    body_latin1 = '{"key": "café"}'.encode("iso-8859-1")
    mock_resp2 = mock.MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.headers = {"content-type": "application/json; charset=iso-8859-1"}
    mock_resp2.iter_bytes.return_value = [body_latin1]
    ms2 = mock.MagicMock()
    ms2.__enter__.return_value = mock_resp2
    ms2.__exit__.return_value = False
    mock_client2 = mock.MagicMock()
    mock_client2.stream.return_value = ms2
    mock_client2.__enter__.return_value = mock_client2
    mock_client2.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client2)
    resp2 = reader.read("http://example.com/data2.json")
    assert "café" in resp2.content
    assert resp2.engine == "raw"


def test_extract_flags_propagate(monkeypatch):
    """include_links/include_tables/precision/recall must reach trafilatura.extract."""
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.reader import WebReader

    html = b"<html><body><article><p>Content with <a href='https://example.com'>link</a> and table.</p></article></body></html>"
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.iter_bytes.return_value = [html]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)

    import trafilatura

    captured = {}

    def fake_extract(text, url=None, output_format=None, include_comments=None, include_tables=None, include_links=None, with_metadata=None, favor_precision=None, favor_recall=None, **kw):
        captured["include_links"] = include_links
        captured["include_tables"] = include_tables
        captured["favor_precision"] = favor_precision
        captured["favor_recall"] = favor_recall
        return "extracted with flags"

    monkeypatch.setattr(trafilatura, "extract", fake_extract)
    monkeypatch.setattr("trafilatura.extract_metadata", lambda *a, **kw: None, raising=False)

    reader = WebReader(cfg)
    resp = reader.read("http://example.com/flags.html", include_links=True, include_tables=False, precision=True, recall=False)
    assert captured["include_links"] is True
    assert captured["include_tables"] is False
    assert captured["favor_precision"] is True
    assert captured["favor_recall"] is False
    assert "extracted" in resp.content

    # second call with opposite flags
    captured.clear()
    resp2 = reader.read("http://example.com/flags2.html", include_links=False, include_tables=True, precision=False, recall=True)
    assert captured["include_links"] is False
    assert captured["include_tables"] is True
    assert captured["favor_precision"] is False
    assert captured["favor_recall"] is True
