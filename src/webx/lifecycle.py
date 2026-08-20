"""Lifecycle — Docker Compose interactions and readiness checks. Minimal stub for Phase 1."""

from __future__ import annotations

import pathlib
import secrets
import shutil
import subprocess
import sys

import httpx

from .config import WebXConfig, get_config
from .errors import DockerUnavailableError, SearxngStartupError
from .models import DoctorReport, RuntimeStatus

# We'll import importlib.resources for assets
try:
    from importlib.resources import files as res_files
except ImportError:
    from importlib_resources import files as res_files  # type: ignore


def _asset_text(name: str) -> str:
    # importlib.resources path: webx.assets/<name>
    p = res_files("webx.assets").joinpath(name)  # type: ignore
    return p.read_text(encoding="utf-8")


def init_runtime(cfg: WebXConfig, *, force_templates: bool = False, show_path: bool = False, verbose: bool = False) -> pathlib.Path:
    """Materialize runtime dir, templates, .env. Idempotent, never rotates secret without explicit reset."""
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    (cfg.cache_dir).mkdir(parents=True, exist_ok=True)

    compose_target = cfg.compose_file
    settings_target = cfg.settings_file
    env_target = cfg.env_file

    wrote = []

    # compose.yml
    if not compose_target.exists() or force_templates:
        text = _asset_text("compose.yml")
        compose_target.write_text(text, encoding="utf-8")
        wrote.append("compose.yml")
        if verbose:
            print(f"wrote {compose_target}", file=sys.stderr)

    # settings.yml
    if not settings_target.exists() or force_templates:
        text = _asset_text("settings.yml")
        settings_target.write_text(text, encoding="utf-8")
        wrote.append("settings.yml")
        if verbose:
            print(f"wrote {settings_target}", file=sys.stderr)

    # .env with secret, never overwrite if exists
    if not env_target.exists():
        secret = secrets.token_hex(32)
        env_text = f"SEARXNG_SECRET={secret}\n"
        env_target.write_text(env_text, encoding="utf-8")
        try:
            env_target.chmod(0o600)
        except Exception:
            pass
        wrote.append(".env")
        if verbose:
            print(f"wrote {env_target}", file=sys.stderr)
    else:
        if verbose:
            print(f"preserve {env_target}", file=sys.stderr)

    if show_path:
        print(str(cfg.runtime_dir))

    # human-readable summary
    if wrote:
        print(f"initialized {cfg.runtime_dir}: {', '.join(wrote)}", file=sys.stderr)
    else:
        print(f"already initialized {cfg.runtime_dir}", file=sys.stderr)

    return cfg.runtime_dir


def probe_http(url: str, timeout: float = 3.0) -> bool:
    """Probe SearXNG root URL. Public for testing."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as c:
            r = c.get(url if url.endswith("/") else url + "/")
            return 200 <= r.status_code < 500  # reachable if not connection error
    except Exception:
        return False


def _probe(url: str, timeout: float = 3.0) -> bool:
    return probe_http(url, timeout)


def _docker_available(cfg: WebXConfig) -> bool:
    return shutil.which(cfg.docker_cmd) is not None


def _compose_version(cfg: WebXConfig) -> str | None:
    try:
        out = subprocess.run(
            [cfg.docker_cmd, "compose", "version", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
        # fallback: docker compose version
        out2 = subprocess.run(
            [cfg.docker_cmd, "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out2.returncode == 0:
            return out2.stdout.strip().splitlines()[0].strip()
        return None
    except Exception:
        return None


def status(cfg: WebXConfig) -> RuntimeStatus:
    initialized = cfg.compose_file.exists() and cfg.settings_file.exists()
    docker_av = _docker_available(cfg)
    running = False
    try:
        running = _probe(cfg.searxng_url, timeout=2.0)
    except Exception:
        running = False
    return RuntimeStatus(
        initialized=initialized,
        docker_available=docker_av,
        searxng_running=running,
        url=cfg.searxng_url,
        runtime_dir=str(cfg.runtime_dir),
    )


def doctor(cfg: WebXConfig) -> DoctorReport:
    import platform

    from . import __version__

    initialized = cfg.compose_file.exists() and cfg.settings_file.exists()
    docker_av = _docker_available(cfg)
    compose_av = False
    compose_ver = None
    docker_err = None
    if docker_av:
        compose_ver = _compose_version(cfg)
        compose_av = compose_ver is not None
        if not compose_av:
            docker_err = "docker compose version failed"
    else:
        docker_err = f"docker not found ({cfg.docker_cmd})"

    templates_present = initialized
    reachable = False
    try:
        reachable = _probe(cfg.searxng_url, timeout=2.0)
    except Exception:
        reachable = False

    # trafilatura version
    traf_ver = None
    try:
        import trafilatura

        traf_ver = getattr(trafilatura, "__version__", "installed")
    except Exception:
        traf_ver = None

    mcp_av = False
    mcp_ver = None
    try:
        import mcp  # type: ignore

        mcp_av = True
        mcp_ver = getattr(mcp, "__version__", "installed")
    except Exception:
        mcp_av = False

    notes: list[str] = []
    if not initialized:
        notes.append("run `webx init` to materialize runtime templates")
    if not reachable and initialized:
        notes.append("SearXNG not reachable — will be lazy-started on next search")

    return DoctorReport(
        python_version=platform.python_version(),
        package_version=__version__,
        runtime_dir=str(cfg.runtime_dir),
        initialized=initialized,
        docker_available=docker_av,
        compose_available=compose_av,
        compose_version=compose_ver,
        templates_present=templates_present,
        searxng_url=cfg.searxng_url,
        searxng_reachable=reachable,
        trafilatura_version=traf_ver,
        mcp_available=mcp_av,
        mcp_version=mcp_ver,
        docker_error=docker_err,
        notes=notes,
    )


def compose_up(cfg: WebXConfig, verbose: bool = False) -> subprocess.CompletedProcess:
    """Run docker compose up -d. Uses list args, no shell.

    Handles the edge where multiple WEBX_DATA_DIR temps share the same container_name
    (webx-searxng) — if Docker reports name conflict, remove the stale container and retry
    once. Production single-runtime is unaffected.
    """
    result = subprocess.run(
        [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "up", "-d"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 and "already in use" in (result.stderr or "") and "webx-searxng" in (result.stderr or ""):
        # Try to remove stale container from a previous temp runtime and retry once
        try:
            subprocess.run([cfg.docker_cmd, "rm", "-f", "webx-searxng"], capture_output=True, text=True, timeout=10)
        except Exception:
            pass
        result = subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "up", "-d"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    return result


def compose_down(cfg: WebXConfig, verbose: bool = False) -> subprocess.CompletedProcess | None:
    """Maintenance: docker compose down."""
    if not cfg.compose_file.exists():
        return None
    return subprocess.run(
        [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "down"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def compose_ps(cfg: WebXConfig, verbose: bool = False) -> subprocess.CompletedProcess | None:
    if not cfg.compose_file.exists():
        return None
    return subprocess.run(
        [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "ps"],
        capture_output=True,
        text=True,
        timeout=10,
    )


# --- lifecycle with polling ---
def ensure_running(cfg: WebXConfig, verbose: bool = False) -> RuntimeStatus:
    """Probe; if not reachable, try docker compose up -d + poll. Minimal for Phase1."""
    if _probe(cfg.searxng_url, timeout=2.0):
        if verbose:
            print(f"SearXNG already running at {cfg.searxng_url}", file=sys.stderr)
        return status(cfg)

    if not _docker_available(cfg):
        raise DockerUnavailableError(f"docker not found ({cfg.docker_cmd})", hint="Install Docker/Compose; webx read still works without SearXNG")

    # ensure templates
    init_runtime(cfg, verbose=verbose)

    # compose up -d (uses helper to keep arg list auditable)
    try:
        result = compose_up(cfg, verbose=verbose)
        if result.returncode != 0:
            raise SearxngStartupError(f"docker compose up failed: {result.stderr or result.stdout}")
    except FileNotFoundError as e:
        raise DockerUnavailableError(f"docker not found: {e}") from e

    # poll
    import time

    deadline = time.time() + cfg.startup_timeout
    last_err = None
    while time.time() < deadline:
        if _probe(cfg.searxng_url, timeout=2.0):
            return status(cfg)
        time.sleep(0.5)
    # timeout — try logs
    logs = ""
    try:
        r = subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "logs", "--tail", "50"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        logs = r.stdout + r.stderr
    except Exception:
        pass
    raise SearxngStartupError(f"SearXNG did not become ready within {cfg.startup_timeout}s at {cfg.searxng_url}", hint=logs[:1000] if logs else None)


def compose_stop(cfg: WebXConfig, verbose: bool = False) -> None:
    if not cfg.compose_file.exists():
        if verbose:
            print("no runtime compose file, nothing to stop", file=sys.stderr)
        return
    if not _docker_available(cfg):
        if verbose:
            print("docker not available, skip stop", file=sys.stderr)
        return
    try:
        subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "stop"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        if verbose:
            print(f"stop error: {e}", file=sys.stderr)
    # idempotent: success even if already stopped



def compose_logs(cfg: WebXConfig, tail: int = 100, verbose: bool = False) -> str:
    if not _docker_available(cfg):
        return "docker not available"
    try:
        r = subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "logs", "--tail", str(tail)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout + r.stderr
    except Exception as e:
        return f"logs error: {e}"
