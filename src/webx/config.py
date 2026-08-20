"""Configuration resolution per 02 Phase 2.

Resolves runtime dir via platformdirs, allows WEBX_* env overrides, provides sane defaults.
Does not require a config file for normal use.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import platformdirs

from .errors import UsageError


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError as e:
        raise UsageError(f"Invalid integer for {name}: {v!r}") from e


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    try:
        return float(v)
    except ValueError as e:
        raise UsageError(f"Invalid float for {name}: {v!r}") from e


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    low = v.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise UsageError(f"Invalid bool for {name}: {v!r}")


@dataclass(slots=True, frozen=True)
class WebXConfig:
    runtime_dir: pathlib.Path
    searxng_url: str
    docker_cmd: str
    startup_timeout: float
    search_timeout: float
    read_timeout: float
    max_response_bytes: int
    max_read_chars: int
    mcp_stop_on_exit: bool

    @property
    def compose_file(self) -> pathlib.Path:
        return self.runtime_dir / "compose.yml"

    @property
    def settings_file(self) -> pathlib.Path:
        return self.runtime_dir / "settings.yml"

    @property
    def env_file(self) -> pathlib.Path:
        return self.runtime_dir / ".env"

    @property
    def cache_dir(self) -> pathlib.Path:
        return self.runtime_dir / "cache"


def get_config() -> WebXConfig:
    """Resolve config from env + platformdirs. Raises UsageError (exit 2) on invalid env."""
    # DATA_DIR
    env_data = os.environ.get("WEBX_DATA_DIR")
    if env_data and env_data.strip():
        runtime_dir = pathlib.Path(env_data).expanduser()
    else:
        # platformdirs user_data_dir for webx
        base = platformdirs.user_data_dir("webx", ensure_exists=False)
        runtime_dir = pathlib.Path(base)

    searxng_url = os.environ.get("WEBX_SEARXNG_URL", "http://127.0.0.1:8888").strip() or "http://127.0.0.1:8888"
    # normalize trailing slash
    searxng_url = searxng_url.rstrip("/")

    docker_cmd = os.environ.get("WEBX_DOCKER_CMD", "docker").strip() or "docker"
    startup_timeout = _env_float("WEBX_STARTUP_TIMEOUT", 30.0)
    search_timeout = _env_float("WEBX_SEARCH_TIMEOUT", 15.0)
    read_timeout = _env_float("WEBX_READ_TIMEOUT", 15.0)
    max_response_bytes = _env_int("WEBX_MAX_RESPONSE_BYTES", 10 * 1024 * 1024)  # 10 MiB
    max_read_chars = _env_int("WEBX_MAX_READ_CHARS", 40000)
    mcp_stop_on_exit = _env_bool("WEBX_MCP_STOP_ON_EXIT", True)

    # hard safety caps (per 05 limits)
    # Search/read timeout must be >0; startup >0; max_bytes at least 1K, at most 100 MiB
    if startup_timeout <= 0 or startup_timeout > 300:
        raise UsageError(f"WEBX_STARTUP_TIMEOUT out of range: {startup_timeout}")
    if search_timeout <= 0 or search_timeout > 120:
        raise UsageError(f"WEBX_SEARCH_TIMEOUT out of range: {search_timeout}")
    if read_timeout <= 0 or read_timeout > 120:
        raise UsageError(f"WEBX_READ_TIMEOUT out of range: {read_timeout}")
    if max_response_bytes < 1024 or max_response_bytes > 100 * 1024 * 1024:
        raise UsageError(f"WEBX_MAX_RESPONSE_BYTES out of range: {max_response_bytes}")
    if max_read_chars < 1000 or max_read_chars > 500000:
        raise UsageError(f"WEBX_MAX_READ_CHARS out of range: {max_read_chars}")

    return WebXConfig(
        runtime_dir=runtime_dir,
        searxng_url=searxng_url,
        docker_cmd=docker_cmd,
        startup_timeout=startup_timeout,
        search_timeout=search_timeout,
        read_timeout=read_timeout,
        max_response_bytes=max_response_bytes,
        max_read_chars=max_read_chars,
        mcp_stop_on_exit=mcp_stop_on_exit,
    )
