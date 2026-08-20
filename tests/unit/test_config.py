import os
import pathlib
import tempfile

def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("WEBX_SEARXNG_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("WEBX_DOCKER_CMD", "podman")
    monkeypatch.setenv("WEBX_STARTUP_TIMEOUT", "45")
    monkeypatch.setenv("WEBX_SEARCH_TIMEOUT", "20")
    monkeypatch.setenv("WEBX_READ_TIMEOUT", "12")
    monkeypatch.setenv("WEBX_MAX_RESPONSE_BYTES", "5000000")
    monkeypatch.setenv("WEBX_MAX_READ_CHARS", "12345")
    monkeypatch.setenv("WEBX_MCP_STOP_ON_EXIT", "0")
    from webx.config import get_config
    cfg = get_config()
    assert cfg.searxng_url == "http://127.0.0.1:9999"
    assert cfg.docker_cmd == "podman"
    assert cfg.startup_timeout == 45.0
    assert cfg.max_response_bytes == 5000000
    assert cfg.max_read_chars == 12345
    assert cfg.mcp_stop_on_exit is False

def test_config_invalid_timeout(monkeypatch):
    monkeypatch.setenv("WEBX_STARTUP_TIMEOUT", "-1")
    from webx.config import get_config
    from webx.errors import UsageError, WebXError

    try:
        get_config()
        assert False, "should raise"
    except (UsageError, WebXError):
        pass
    except ValueError:
        # Backwards compat: UsageError is now raised, but ValueError was previously expected
        pass

def test_config_default_url_stripped(monkeypatch):
    monkeypatch.delenv("WEBX_SEARXNG_URL", raising=False)
    from webx.config import get_config
    cfg = get_config()
    assert cfg.searxng_url == "http://127.0.0.1:8888"

def test_init_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx"))
    from webx.config import get_config
    from webx.lifecycle import init_runtime
    cfg = get_config()
    p1 = init_runtime(cfg)
    secret1 = (cfg.env_file).read_text()
    # second run preserves secret
    init_runtime(cfg)
    secret2 = (cfg.env_file).read_text()
    assert secret1 == secret2
    # force-templates does not rotate secret either
    init_runtime(cfg, force_templates=True)
    secret3 = (cfg.env_file).read_text()
    assert secret1 == secret3
    # files exist
    assert cfg.compose_file.exists()
    assert cfg.settings_file.exists()
    assert cfg.cache_dir.exists()

def test_init_show_path(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx2"))
    from webx.config import get_config
    from webx.lifecycle import init_runtime
    cfg = get_config()
    init_runtime(cfg, show_path=True)
    out = capsys.readouterr()
    # show_path prints runtime dir to stdout
    assert str(cfg.runtime_dir) in out.out or str(cfg.runtime_dir) in out.err
