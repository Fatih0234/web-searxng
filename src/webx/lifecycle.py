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
    """Probe SearXNG root URL. Public for testing.

    Requires 2xx (preferably 200) to consider the service healthy; 4xx
    (e.g. 403/404 from an intercepting proxy or misconfigured instance)
    must not be treated as running.
    Uses trust_env=False to avoid proxy-mediated false positives.
    """
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as c:
            r = c.get(url if url.endswith("/") else url + "/")
            return 200 <= r.status_code < 300
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


def _searxng_image(cfg: WebXConfig) -> str | None:
    """Return the SearXNG image that will be used (from compose or env override)."""
    # Env override takes precedence
    import os

    env = os.environ.get("SEARXNG_IMAGE")
    if env:
        return env
    # Parse compose file for default
    try:
        if cfg.compose_file.exists():
            txt = cfg.compose_file.read_text(encoding="utf-8")
            for line in txt.splitlines():
                if "image:" in line and "searxng" in line:
                    # e.g. "    image: ${SEARXNG_IMAGE:-docker.io/searxng/searxng:2026.8.19-5ffd32ca2}"
                    # Extract default after :-
                    if ":-" in line:
                        start = line.index(":-") + 2
                        end = line.index("}", start)
                        return line[start:end].strip()
                    # Fallback: raw after "image:"
                    return line.split("image:", 1)[1].strip().strip('"').strip("'")
        # Fallback to asset
        txt = _asset_text("compose.yml")
        for line in txt.splitlines():
            if "image:" in line and "searxng" in line and ":-" in line:
                start = line.index(":-") + 2
                end = line.index("}", start)
                return line[start:end].strip()
    except Exception:
        pass
    return None


def _searxng_version(cfg: WebXConfig) -> str | None:
    """Try to get SearXNG version via /config or via image tag."""
    # Try /config admin API if reachable
    try:
        import httpx as _httpx

        url = cfg.searxng_url.rstrip("/") + "/config"
        with _httpx.Client(timeout=2.0, follow_redirects=False, trust_env=False) as c:
            r = c.get(url)
            if r.status_code == 200:
                try:
                    j = r.json()
                    # SearXNG /config may contain version fields
                    for key in ("version", "searxng_version", "searxng", "instance_name"):
                        if isinstance(j, dict) and key in j and isinstance(j[key], str):
                            return j[key]
                    # Sometimes engines dict indicates version indirectly; return image tag instead
                except Exception:
                    pass
    except Exception:
        pass
    # Fallback: derive version from image tag
    img = _searxng_image(cfg)
    if img and ":" in img:
        tag = img.rsplit(":", 1)[-1]
        # strip digest if present
        if "@" in tag:
            tag = tag.split("@")[0]
        return tag
    return None


def status(cfg: WebXConfig) -> RuntimeStatus:
    compose_exists = cfg.compose_file.exists()
    initialized = compose_exists and cfg.settings_file.exists()
    docker_av = _docker_available(cfg)
    running = False
    try:
        running = _probe(cfg.searxng_url, timeout=2.0)
    except Exception:
        running = False
    img = _searxng_image(cfg)
    ver: str | None = None
    if img and ":" in img:
        ver = img.rsplit(":", 1)[-1].split("@")[0]
    if running:
        try:
            cfg_ver = _searxng_version(cfg)
            if cfg_ver:
                ver = cfg_ver
        except Exception:
            pass
    return RuntimeStatus(
        initialized=initialized,
        docker_available=docker_av,
        searxng_running=running,
        url=cfg.searxng_url,
        runtime_dir=str(cfg.runtime_dir),
        compose_exists=compose_exists,
        searxng_image=img,
        searxng_version=ver,
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
    # SearXNG image/version observability
    searxng_img = _searxng_image(cfg)
    searxng_ver: str | None = None
    if reachable:
        try:
            searxng_ver = _searxng_version(cfg)
        except Exception:
            searxng_ver = None
    else:
        # Not running: version is image tag
        if searxng_img and ":" in searxng_img:
            tag = searxng_img.rsplit(":", 1)[-1]
            searxng_ver = tag.split("@")[0] if "@" in tag else tag
    if searxng_img and "latest" in searxng_img:
        notes.append("SearXNG image is :latest — pin to a versioned tag for reproducibility (SEARXNG_IMAGE env)")
    # Check for engine suspension hint via /search?format=json quick probe (optional, non-fatal)
    if reachable:
        try:
            import httpx as _httpx2

            with _httpx2.Client(timeout=2.0, trust_env=False) as c:
                r = c.get(cfg.searxng_url.rstrip("/") + "/config", follow_redirects=False)
                # If /config is accessible, it helps distinguish WebX vs upstream failures
                if r.status_code == 200:
                    notes.append("SearXNG /config accessible — use for engine suspension diagnostics (see https://docs.searxng.org/admin/api.html)")
        except Exception:
            pass

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
        searxng_image=searxng_img,
        searxng_version=searxng_ver,
    )


def compose_up(cfg: WebXConfig, verbose: bool = False) -> subprocess.CompletedProcess:
    """Run docker compose up -d. Uses list args, no shell.

    On container-name collision (e.g. "webx-searxng already in use"),
    this function no longer performs destructive ``docker rm -f``.
    A collision indicates another WebX instance or stale container may be
    active; automatically deleting it would violate the non-destructive
    guarantee for implicit ``search`` startup. Callers should surface the
    error so the user can inspect with ``docker ps`` / ``webx logs`` and
    run an explicit ``webx down`` / ``docker rm`` if cleanup is desired.
    """
    return subprocess.run(
        [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "up", "-d"],
        capture_output=True,
        text=True,
        timeout=30,
    )


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
            msg = result.stderr or result.stdout or ""
            if "already in use" in msg and "webx-searxng" in msg:
                raise SearxngStartupError(
                    f"docker compose up failed: container webx-searxng already in use: {msg.strip()}",
                    hint="another WebX instance may be running — inspect with `docker ps -a --filter name=webx-searxng` and `docker logs webx-searxng`; remove only with explicit `docker rm -f webx-searxng` or `webx down` if safe",
                )
            raise SearxngStartupError(f"docker compose up failed: {msg.strip()}")
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


def compose_stop(cfg: WebXConfig, verbose: bool = False) -> subprocess.CompletedProcess | None:
    """Stop SearXNG via ``docker compose stop``. Idempotent when already stopped.

    Raises a typed :class:`WebXError` on genuine failure (non-zero exit,
    docker unavailable, etc.) so callers can distinguish success from
    failure. Already-stopped is success (compose returns 0).
    """
    from .errors import RuntimeError as WebXRuntimeError

    if not cfg.compose_file.exists():
        if verbose:
            print("no runtime compose file, nothing to stop", file=sys.stderr)
        return None
    if not _docker_available(cfg):
        if verbose:
            print("docker not available, skip stop", file=sys.stderr)
        return None
    try:
        result = subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "stop"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as e:
        raise WebXRuntimeError(f"docker not found: {e}", hint="Install Docker/Compose") from e
    except Exception as e:
        if verbose:
            print(f"stop error: {e}", file=sys.stderr)
        raise WebXRuntimeError(f"docker compose stop failed: {e}") from e
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        raise WebXRuntimeError(
            f"docker compose stop failed (exit {result.returncode}): {msg}",
            hint="check `docker ps` and `webx logs`",
        )
    # idempotent: already stopped returns 0, so success
    return result



def compose_logs(cfg: WebXConfig, tail: int = 100, verbose: bool = False) -> str:
    if not cfg.compose_file.exists():
        return "no runtime compose file — run `webx init` to materialize templates"
    if not _docker_available(cfg):
        return "docker not available"
    try:
        r = subprocess.run(
            [cfg.docker_cmd, "compose", "-f", str(cfg.compose_file), "logs", "--tail", str(tail)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (r.stdout or "") + (r.stderr or "")
        if output.strip():
            return output
        # Empty output — distinguish stopped vs error.
        # When compose file missing or service not running, docker compose logs is empty with returncode 0.
        # Provide hint instead of silent empty.
        try:
            running = _probe(cfg.searxng_url, timeout=2.0)
        except Exception:
            running = False
        if not running:
            # Also check if compose file itself missing — more precise hint
            if not cfg.compose_file.exists():
                return "no runtime compose file — run `webx init` to materialize templates"
            return "SearXNG not running — no container logs (run `webx up` or `webx search` to start)"
        # Running but no logs yet (fresh container) — return empty-ish but not hint
        return output if output else "(no logs yet)"
    except Exception as e:
        return f"logs error: {e}"
