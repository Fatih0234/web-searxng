import socket
from unittest import mock
import pytest

from webx.errors import UnsafeUrlError
from webx.security import validate_url
from webx.config import WebXConfig
import pathlib

def make_cfg():
    return WebXConfig(
        runtime_dir=pathlib.Path("/tmp/webx-sec-test"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10*1024*1024,
        max_read_chars=40000,
        mcp_stop_on_exit=True,
    )

def test_allow_public_with_mock(monkeypatch):
    cfg = make_cfg()
    # Mock getaddrinfo to return public IP 93.184.215.14 (example.com)
    def fake_getaddrinfo(host, *a, **kw):
        if host == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]
        raise socket.gaierror("not found")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    # should allow
    validate_url("http://example.com", cfg)
    validate_url("https://example.com/path?x=1", cfg)

def test_deny_schemes(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14",0))])
    for url in ["file:///etc/passwd", "ftp://example.com", "data:text/plain,hello", "javascript:alert(1)", "/etc/passwd"]:
        with pytest.raises(UnsafeUrlError):
            validate_url(url, cfg)

def test_deny_localhost_and_loopback(monkeypatch):
    cfg = make_cfg()
    # no need to mock DNS for literal IP case - _check_hostname_literal will deny directly
    # but we also mock to ensure no bypass
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1",0))])
    for url in ["http://localhost", "http://localhost:8000", "http://127.0.0.1", "http://127.0.0.1:8888", "http://127.0.0.1:8000/path", "http://[::1]", "http://[::1]:8888"]:
        with pytest.raises(UnsafeUrlError, match="disallowed"):
            validate_url(url, cfg)

def test_deny_private_ranges(monkeypatch):
    cfg = make_cfg()
    # For literal IP URLs, check directly without DNS
    for url in ["http://10.0.0.1", "http://10.5.6.7", "http://172.16.0.1", "http://172.31.255.255", "http://192.168.1.1", "http://192.168.0.5:3000"]:
        with pytest.raises(UnsafeUrlError):
            validate_url(url, cfg)
    # Also test via DNS: hostname that resolves to private
    def fake_priv(host, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_priv)
    with pytest.raises(UnsafeUrlError):
        validate_url("http://example.com", cfg)

def test_deny_metadata_and_link_local(monkeypatch):
    cfg = make_cfg()
    for url in ["http://169.254.169.254", "http://169.254.1.1", "http://[fe80::1]"]:
        with pytest.raises(UnsafeUrlError):
            validate_url(url, cfg)

def test_deny_private_ipv6(monkeypatch):
    cfg = make_cfg()
    # fc00:: is unique local
    for url in ["http://[fc00::1]", "http://[fd00::1]"]:
        with pytest.raises(UnsafeUrlError):
            validate_url(url, cfg)

def test_deny_credentials(monkeypatch):
    cfg = make_cfg()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14",0))])
    for url in ["http://user:pass@example.com", "https://user@example.com"]:
        with pytest.raises(UnsafeUrlError, match="credentials"):
            validate_url(url, cfg)

def test_deny_multicast_unspecified(monkeypatch):
    cfg = make_cfg()
    for url in ["http://224.0.0.1", "http://0.0.0.0", "http://255.255.255.255"]:
        with pytest.raises(UnsafeUrlError):
            validate_url(url, cfg)

def test_allow_public_literal_ip(monkeypatch):
    cfg = make_cfg()
    # public literal IP should be allowed if not denied
    # 8.8.8.8 is public
    # Need to mock getaddrinfo to not trigger private? For literal IP, _check_hostname_literal will check, but 8.8.8.8 is not denied, so it passes, then _resolve_and_check will also be called via getaddrinfo which returns 8.8.8.8
    monkeypatch.setattr(socket, "getaddrinfo", lambda h, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (h,0))])
    validate_url("http://8.8.8.8", cfg)
    validate_url("https://1.1.1.1/path", cfg)
