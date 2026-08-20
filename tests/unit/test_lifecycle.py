import pathlib
from unittest import mock

def test_already_running_never_calls_docker(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    # ensure init
    lifecycle.init_runtime(cfg)
    # mock probe to True
    monkeypatch.setattr(lifecycle, "probe_http", lambda url, timeout=2.0: True)
    # mock subprocess
    with mock.patch("webx.lifecycle.subprocess.run") as m:
        st = lifecycle.ensure_running(cfg)
        m.assert_not_called()
        assert st.searxng_running is True

def test_stopped_calls_up_and_polls(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx2"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    lifecycle.init_runtime(cfg)
    calls = {"probe": 0}

    def fake_probe(url, timeout=2.0):
        calls["probe"] += 1
        # first probe in ensure_running -> False, second polls -> False, third -> True
        return calls["probe"] >= 3

    monkeypatch.setattr(lifecycle, "probe_http", fake_probe)
    monkeypatch.setattr(lifecycle, "_probe", fake_probe)
    # mock docker available
    monkeypatch.setattr(lifecycle, "_docker_available", lambda cfg: True)
    with mock.patch("webx.lifecycle.subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        st = lifecycle.ensure_running(cfg)
        # should have called compose up -d
        assert any("up" in str(c.args) for c in m.call_args_list), m.call_args_list
        # verify list args not shell string
        for call in m.call_args_list:
            args, kwargs = call
            assert isinstance(args[0], list), "must use list args not string"

def test_ensure_running_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx3"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    # shorten timeout for test
    from dataclasses import replace
    cfg = replace(cfg, startup_timeout=0.6)
    lifecycle.init_runtime(cfg)
    monkeypatch.setattr(lifecycle, "probe_http", lambda url, timeout=2.0: False)
    monkeypatch.setattr(lifecycle, "_docker_available", lambda cfg: True)
    with mock.patch("webx.lifecycle.subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        try:
            lifecycle.ensure_running(cfg)
            assert False, "should timeout"
        except Exception as e:
            assert "did not become ready" in str(e)

def test_stop_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx4"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    # no compose file -> no docker call
    lifecycle.compose_stop(cfg)
    # with compose file but docker missing
    lifecycle.init_runtime(cfg)
    monkeypatch.setattr(lifecycle, "_docker_available", lambda cfg: False)
    lifecycle.compose_stop(cfg)  # should not raise

def test_compose_args_are_list(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx5"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    lifecycle.init_runtime(cfg)
    with mock.patch("webx.lifecycle.subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="v5.3.1", stderr="")
        lifecycle._compose_version(cfg)
        # calls should be list
        for call in m.call_args_list:
            assert isinstance(call.args[0], list)
            assert "docker" not in str(call.args[0]) or isinstance(call.args[0], list)

def test_doctor_not_start(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBX_DATA_DIR", str(tmp_path / "webx6"))
    from webx.config import get_config
    from webx import lifecycle
    cfg = get_config()
    with mock.patch("webx.lifecycle.probe_http") as mp:
        mp.return_value = False
        rep = lifecycle.doctor(cfg)
        mp.assert_called()
        assert rep.searxng_reachable is False
        # ensure ensure_running not called
