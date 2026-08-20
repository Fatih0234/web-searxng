import json
import pathlib
import socket
from unittest import mock
import pytest

def make_cfg(tmp_path):
    from webx.config import WebXConfig
    return WebXConfig(
        runtime_dir=pathlib.Path(tmp_path / "webx"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10*1024*1024,
        max_read_chars=40000,
        mcp_stop_on_exit=True,
    )

def fake_public(host, *a, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14",0))]

def test_cli_read_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-json"))
    monkeypatch.setattr(socket, "getaddrinfo", fake_public)
    from webx.lifecycle import init_runtime
    from webx.config import get_config
    cfg = get_config()
    init_runtime(cfg)
    # mock httpx
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    html = b"<html><body><article><p>Test content for json</p></article></body></html>"
    mock_resp.iter_bytes.return_value = [html]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    from webx.cli import main
    ret = main(["read", "http://example.com", "--json"])
    assert ret == 0
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert data["url"] == "http://example.com"
    assert "content" in data
    assert data["truncated"] is False

def test_cli_read_unsafe_exit_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-unsafe"))
    from webx.cli import main
    # literal private IP doesn't need DNS mock, validation will deny
    ret = main(["read", "http://192.168.1.1/"])
    assert ret == 5
    out, err = capsys.readouterr()
    assert "error" in err.lower()

def test_cli_search_invalid_limit(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-limit"))
    from webx.cli import main
    ret = main(["search", "hello", "--limit", "100"])
    assert ret == 2
    ret2 = main(["search", "hello", "--limit", "0"])
    assert ret2 == 2

def test_cli_status_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-status"))
    from webx.lifecycle import init_runtime
    from webx.config import get_config
    cfg = get_config()
    init_runtime(cfg)
    monkeypatch.setattr(socket, "getaddrinfo", fake_public)
    # mock probe to False
    from webx import lifecycle
    monkeypatch.setattr(lifecycle, "probe_http", lambda url, timeout=2.0: False)
    from webx.cli import main
    ret = main(["status", "--json"])
    assert ret == 0
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert "initialized" in data
    assert data["initialized"] is True

def test_cli_doctor_not_start(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-doc"))
    from webx import lifecycle
    with mock.patch("webx.lifecycle.probe_http") as mp:
        mp.return_value = False
        from webx.cli import main
        ret = main(["doctor"])
        assert ret == 0
        mp.assert_called()

def test_cli_read_unsupported_type(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-unsup"))
    monkeypatch.setattr(socket, "getaddrinfo", fake_public)
    from webx.config import get_config
    from webx.lifecycle import init_runtime
    cfg = get_config()
    init_runtime(cfg)
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/pdf"}
    mock_resp.iter_bytes.return_value = [b"%PDF"]
    ms = mock.MagicMock()
    ms.__enter__.return_value = mock_resp
    ms.__exit__.return_value = False
    mock_client = mock.MagicMock()
    mock_client.stream.return_value = ms
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    monkeypatch.setattr("webx.reader.httpx.Client", lambda *a, **kw: mock_client)
    from webx.cli import main
    ret = main(["read", "http://example.com/file.pdf"])
    assert ret == 7

def test_cli_logs(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx-logs"))
    from webx.config import get_config
    from webx.lifecycle import init_runtime
    cfg = get_config()
    init_runtime(cfg)
    from unittest import mock
    with mock.patch("webx.lifecycle.subprocess.run") as m:
        m.return_value = mock.Mock(stdout="log line", stderr="", returncode=0)
        # also mock docker available
        from webx import lifecycle
        monkeypatch.setattr(lifecycle, "_docker_available", lambda cfg: True)
        from webx.cli import main
        ret = main(["logs", "--tail", "10"])
        assert ret == 0
        out, err = capsys.readouterr()
        assert "log line" in out
