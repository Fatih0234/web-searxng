import pathlib
import socket
from unittest import mock
import pytest

from webx.config import WebXConfig
from webx.errors import FetchError, UnsupportedContentTypeError, UnsafeUrlError, ExtractionError

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
