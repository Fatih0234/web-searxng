def test_import():
    import webx
    assert webx.__version__

def test_config_defaults():
    import os
    os.environ.pop("WEBX_DATA_DIR", None)
    from webx.config import get_config
    cfg = get_config()
    assert cfg.searxng_url == "http://127.0.0.1:8888"
    assert cfg.max_read_chars == 40000

def test_cli_help():
    from webx.cli import _build_parser
    p = _build_parser()
    # ensure all commands registered
    assert "search" in p._subparsers._group_actions[0].choices
    assert "read" in p._subparsers._group_actions[0].choices

def test_assets_present():
    from importlib.resources import files
    assert (files("webx.assets") / "compose.yml").is_file()
    assert (files("webx.assets") / "settings.yml").is_file()
    import pathlib
    text = (files("webx.assets") / "compose.yml").read_text()
    assert "127.0.0.1:8888:8080" in text
    text2 = (files("webx.assets") / "settings.yml").read_text()
    assert "use_default_settings: true" in text2
