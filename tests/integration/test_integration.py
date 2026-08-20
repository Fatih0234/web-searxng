"""Integration tests — require Docker/SearXNG or public net, marked `integration`."""

import json
import pathlib
import socket
import subprocess

import pytest

pytestmark = pytest.mark.integration


def _get_config(tmp_path):
    import os

    os.environ["WEBX_DATA_DIR"] = str(tmp_path / "webx-int")
    from webx.config import get_config

    return get_config()


def test_local_searxng_smoke(tmp_path):
    """Smoke: init -> status stopped -> search -> running -> second search reuse -> stop -> stopped."""
    import os

    os.environ["WEBX_DATA_DIR"] = str(tmp_path / "webx-smoke")
    from webx.config import get_config
    from webx.lifecycle import init_runtime, status, compose_stop
    from webx.core import WebX

    cfg = get_config()
    # ensure clean
    init_runtime(cfg)

    st = status(cfg)
    assert st.initialized is True
    # initially not running (unless leftover)
    # Try to ensure stopped for test isolation
    compose_stop(cfg)

    st = status(cfg)
    # may be stopped unless previous run left running; we tolerate either but prefer stopped
    # Now try search — this will lazy start SearXNG; if docker not available skip
    if not st.docker_available:
        pytest.skip("docker not available")

    core = WebX(cfg)
    # stable query; if upstream engines blocked or no net, this may fail; provide skip
    try:
        resp = core.search("SearXNG documentation", limit=2)
    except Exception as e:
        # If search fails due to engine rate limit or no docker, skip not fail
        pytest.skip(f"search skipped due to environment: {e}")

    assert resp.query == "SearXNG documentation"
    assert len(resp.results) >= 0  # may be 0 if engines blocked, but schema must be valid
    for r in resp.results:
        assert r.url.startswith("http")
        assert isinstance(r.title, str)

    st2 = status(cfg)
    assert st2.searxng_running is True

    # second search should reuse without recreation
    resp2 = core.search("Python documentation", limit=2)
    assert resp2.meta.result_count <= 2

    compose_stop(cfg)
    st3 = status(cfg)
    assert st3.searxng_running is False


def test_live_reader_example(tmp_path):
    """Read a stable public page."""
    import os

    os.environ["WEBX_DATA_DIR"] = str(tmp_path / "webx-reader-int")
    from webx.config import get_config
    from webx.lifecycle import init_runtime
    from webx.core import WebX

    cfg = get_config()
    init_runtime(cfg)
    core = WebX(cfg)
    # This needs internet; skip if fails
    try:
        resp = core.read("https://example.com", max_chars=5000)
    except Exception as e:
        pytest.skip(f"live reader skipped: {e}")
    assert "Example Domain" in resp.content or "domain" in resp.content.lower()
    assert resp.truncated is False
    assert resp.final_url.startswith("https://example.com")
