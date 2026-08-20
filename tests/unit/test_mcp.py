import pathlib
import socket
from unittest import mock
import pytest

def fake_public_getaddrinfo(*a, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14",0))]

@pytest.mark.asyncio
async def test_mcp_exactly_two_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "mcp1"))
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    # ensure clean state
    import webx.mcp_server as mcp_mod
    mcp_mod._started_by_mcp = None
    server = mcp_mod.create_server()
    tools = await server.list_tools()
    names = sorted(t.name for t in tools)
    assert names == ["web_read", "web_search"]
    assert len(tools) == 2

@pytest.mark.asyncio
async def test_mcp_launch_does_not_start(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "mcp2"))
    import webx.mcp_server as mcp_mod
    mcp_mod._started_by_mcp = None
    # mock probe to ensure not called at launch
    with mock.patch("webx.mcp_server.probe_http") as mp_probe:
        server = mcp_mod.create_server()
        # creating server should not probe
        mp_probe.assert_not_called()
        # also ensure SearXNG not running via lifecycle probe
        from webx.lifecycle import probe_http as real_probe
        # but our mock is for mcp_server.probe_http, not lifecycle; still should not have started
        assert mcp_mod._started_by_mcp is None

@pytest.mark.asyncio
async def test_mcp_web_search_starts_and_read_does_not(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "mcp3"))
    import webx.mcp_server as mcp_mod
    mcp_mod._started_by_mcp = None
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    # mock webx.core search/read
    mock_search_resp = mock.MagicMock()
    mock_search_resp.to_dict.return_value = {"query": "hello", "results": [], "meta": {"result_count":0}}
    mock_read_resp = mock.MagicMock()
    mock_read_resp.to_dict.return_value = {"url": "http://example.com", "content": "hi"}
    with mock.patch("webx.mcp_server.WebX") as MockWebX:
        inst = MockWebX.return_value
        inst.search.return_value = mock_search_resp
        inst.read.return_value = mock_read_resp
        # mock ensure_running via _ensure_started_flag to avoid docker
        with mock.patch("webx.mcp_server._ensure_started_flag") as m_ensure:
            m_ensure.return_value = True
            server = mcp_mod.create_server()
            # call web_read -> should not call ensure
            result = await server.call_tool("web_read", {"url": "http://example.com"})
            # web_read should call read, not ensure
            inst.read.assert_called_once()
            m_ensure.assert_not_called()
            # reset
            inst.read.reset_mock()
            # call web_search -> should call ensure
            result2 = await server.call_tool("web_search", {"query": "hello"})
            m_ensure.assert_called_once()
            inst.search.assert_called_once()

@pytest.mark.asyncio
async def test_mcp_ownership(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "mcp4"))
    import webx.mcp_server as mcp_mod
    mcp_mod._started_by_mcp = None
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    # Test that first search when already running leaves flag False, and cleanup does not stop
    with mock.patch("webx.mcp_server.probe_http", return_value=True) as mp_probe:
        with mock.patch("webx.mcp_server.WebX") as MockWebX:
            mock_search_resp = mock.MagicMock()
            mock_search_resp.to_dict.return_value = {"query":"q","results":[]}
            MockWebX.return_value.search.return_value = mock_search_resp
            # need to not mock _ensure, let it use real logic but with mocked probe
            # Patch lifecycle.ensure_running to not actually run docker
            with mock.patch("webx.lifecycle.ensure_running") as m_up:
                server = mcp_mod.create_server()
                # Call search - should see probe True -> not start
                await server.call_tool("web_search", {"query": "q"})
                m_up.assert_not_called()
                assert mcp_mod._started_by_mcp is False
                # cleanup should not call compose_stop because flag False
                with mock.patch("webx.mcp_server.compose_stop") as m_stop:
                    mcp_mod._cleanup_mcp_if_needed()
                    m_stop.assert_not_called()
    # Now test when not running -> start flag True and cleanup stops
    mcp_mod._started_by_mcp = None
    with mock.patch("webx.mcp_server.probe_http", return_value=False) as mp_probe2:
        with mock.patch("webx.lifecycle.ensure_running") as m_up2:
            with mock.patch("webx.mcp_server.WebX") as MockWebX2:
                mock_search_resp2 = mock.MagicMock()
                mock_search_resp2.to_dict.return_value = {"query":"q","results":[]}
                MockWebX2.return_value.search.return_value = mock_search_resp2
                server2 = mcp_mod.create_server()
                await server2.call_tool("web_search", {"query":"q"})
                m_up2.assert_called_once()
                assert mcp_mod._started_by_mcp is True
                with mock.patch("webx.mcp_server.compose_stop") as m_stop2:
                    # Need to mock get_config to have mcp_stop_on_exit True
                    mcp_mod._started_by_mcp = True
                    # ensure config has stop_on_exit True (default)
                    mcp_mod._cleanup_mcp_if_needed()
                    m_stop2.assert_called_once()
                # also test when stop_on_exit False, no stop
                mcp_mod._started_by_mcp = True
                with mock.patch("webx.mcp_server.get_config") as m_cfg:
                    fake_cfg = mock.MagicMock()
                    fake_cfg.mcp_stop_on_exit = False
                    fake_cfg.runtime_dir = pathlib.Path("/tmp")
                    m_cfg.return_value = fake_cfg
                    with mock.patch("webx.mcp_server.compose_stop") as m_stop3:
                        mcp_mod._cleanup_mcp_if_needed()
                        m_stop3.assert_not_called()
                mcp_mod._started_by_mcp = None

def test_mcp_error_mapping(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "mcp5"))
    import webx.mcp_server as mcp_mod
    mcp_mod._started_by_mcp = None
    monkeypatch.setattr(socket, "getaddrinfo", fake_public_getaddrinfo)
    from webx.errors import UnsafeUrlError
    import asyncio
    async def run():
        server = mcp_mod.create_server()
        # Mock WebX.read to raise UnsafeUrlError
        with mock.patch("webx.mcp_server.WebX") as MockWebX:
            inst = MockWebX.return_value
            inst.read.side_effect = UnsafeUrlError("unsafe")
            try:
                await server.call_tool("web_read", {"url": "http://192.168.1.1"})
                assert False, "should raise"
            except Exception as e:
                # ToolError will be wrapped; check message contains unsafe
                assert "unsafe" in str(e).lower() or "disallowed" in str(e).lower()
    asyncio.run(run())
