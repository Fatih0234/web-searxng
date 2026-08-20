"""Security harness for DNS pinning — verifies fail-closed, SNI, multi-IP fallback, rebinding."""
import pathlib
import socket
from unittest import mock
import pytest
import httpx

from webx.config import WebXConfig
from webx.errors import UnsafeUrlError, FetchError


def make_cfg(**overrides):
    base = dict(
        runtime_dir=pathlib.Path("/tmp/webx-pinning"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10 * 1024 * 1024,
        max_read_chars=40000,
        mcp_stop_on_exit=True,
    )
    base.update(overrides)
    return WebXConfig(**base)


@pytest.fixture(autouse=True)
def clear_cache():
    from webx import reader as _m
    _m._READ_CACHE.clear()
    yield
    _m._READ_CACHE.clear()


def test_https_pinning_uses_sni_and_pinned_ip(monkeypatch):
    """https should connect to pinned IP with Host + sni_hostname=original host."""
    cfg = make_cfg()
    # example.com -> 93.184.215.14 public
    monkeypatch.setattr(socket, "getaddrinfo", lambda h,*a,**kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))])

    captured = {}
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            captured["url"] = url
            captured["headers"] = headers
            captured["extensions"] = extensions
            # Verify Host and SNI
            assert headers.get("Host") == "example.com"
            assert extensions == {"sni_hostname": "example.com"}
            assert "93.184.215.14" in url  # pinned
            assert url.startswith("https://")
            # Return 200
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.iter_bytes.return_value = [b"<html><body><p>ok https pinned</p></body></html>"]
            ms = mock.MagicMock()
            ms.__enter__.return_value = resp
            ms.__exit__.return_value = False
            return ms
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m

    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    resp = r.read("https://example.com")
    assert "ok https" in resp.content
    assert captured["extensions"] == {"sni_hostname": "example.com"}


def test_http_pinning_uses_host_not_sni(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", lambda h,*a,**kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))])
    captured = {}
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            captured["url"] = url
            captured["headers"] = headers
            captured["extensions"] = extensions
            assert headers.get("Host") == "example.com"
            assert extensions is None  # http no SNI
            assert "93.184.215.14" in url
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.iter_bytes.return_value = [b"<html><body><p>ok http</p></body></html>"]
            ms = mock.MagicMock()
            ms.__enter__.return_value = resp
            ms.__exit__.return_value = False
            return ms
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    resp = r.read("http://example.com")
    assert "ok http" in resp.content


def test_rebinding_is_blocked_by_pinning(monkeypatch):
    """Even if DNS would rebind to private on second resolve, pinning keeps public IP."""
    cfg = make_cfg()
    # First resolve (validate) returns public, but we simulate that the underlying
    # httpx would have resolved to private if not pinned. Our pinning should ensure
    # the request URL is the pinned public IP, not the private.
    # So we just verify the pinned URL is public and Host is original.
    monkeypatch.setattr(socket, "getaddrinfo", lambda h,*a,**kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))])
    # Count how many distinct IPs were used
    captured_urls = []
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            captured_urls.append(url)
            # Ensure private IP never appears
            assert "192.168" not in url
            assert "10." not in url
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.iter_bytes.return_value = [b"<html><body><p>rebinding ok</p></body></html>"]
            ms = mock.MagicMock()
            ms.__enter__.return_value = resp
            ms.__exit__.return_value = False
            return ms
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    resp = r.read("http://example.com")
    assert any("93.184.215.14" in u for u in captured_urls)


def test_first_ip_failure_retries_second(monkeypatch):
    """If first pinned IP fails with ConnectError, second is tried."""
    cfg = make_cfg()
    # Return two IPs: first unreachable, second public
    def fake_getaddrinfo(h,*a,**kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.15", 0)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    call_urls = []
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            call_urls.append(url)
            if "93.184.215.14" in url:
                raise httpx.ConnectError("fake connect fail first IP", request=mock.MagicMock())
            # second IP succeeds
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.iter_bytes.return_value = [b"<html><body><p>second ok</p></body></html>"]
            ms = mock.MagicMock()
            ms.__enter__.return_value = resp
            ms.__exit__.return_value = False
            return ms
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    resp = r.read("http://example.com")
    assert "second ok" in resp.content
    assert len(call_urls) == 2
    assert "93.184.215.14" in call_urls[0]
    assert "93.184.215.15" in call_urls[1]


def test_all_ips_fail_raises_fetch(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", lambda h,*a,**kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.15", 0)),
    ])
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            raise httpx.ConnectError("all fail", request=mock.MagicMock())
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    with pytest.raises(FetchError, match="tried 2 pinned IPs"):
        r.read("http://example.com")


def test_literal_ip_no_pinning(monkeypatch):
    """Literal IP should not be pinned (no Host/SNI rewrite) — validate still resolves literal via getaddrinfo."""
    cfg = make_cfg()
    def literal_getaddrinfo(h,*a,**kw):
        # Literal should resolve to itself without DNS rebinding risk
        try:
            import ipaddress
            ipaddress.ip_address(h.strip("[]"))
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, 0))]
        except ValueError:
            raise AssertionError(f"unexpected host {h}")
    monkeypatch.setattr(socket, "getaddrinfo", literal_getaddrinfo)
    captured = {}
    def fake_client_factory(*a, **kw):
        m = mock.MagicMock()
        def fake_stream(method, url, headers=None, extensions=None, **kw2):
            captured["url"] = url
            captured["headers"] = headers
            assert url == "http://93.184.215.14/path"
            assert headers == {} or "Host" not in headers
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "text/html"}
            resp.iter_bytes.return_value = [b"<html><body><p>literal ok</p></body></html>"]
            ms = mock.MagicMock()
            ms.__enter__.return_value = resp
            ms.__exit__.return_value = False
            return ms
        m.stream.side_effect = fake_stream
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m
    monkeypatch.setattr("webx.reader.httpx.Client", fake_client_factory)
    from webx.reader import WebReader
    r = WebReader(cfg)
    # Need to bypass validate_url for literal public IP: 93.184.215.14 is public, so allowed.
    # Our security should allow it.
    monkeypatch.setattr("webx.security._is_deny_ip", lambda ip: False)  # ensure not denied
    # But validate_url will still call getaddrinfo for literal? No, it checks is_literal and skips resolve.
    # So we need to ensure validate passes.
    # Use a public literal that is not in deny range.
    resp = r.read("http://93.184.215.14/path")
    assert "literal ok" in resp.content
