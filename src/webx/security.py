"""Security — URL parsing, hostname/IP checks, redirect validation, private-network denial."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

from .config import WebXConfig
from .errors import UnsafeUrlError


# Explicit deny hosts (case-insensitive)
_DENY_HOSTS = {"localhost", "localhost.", "broadcasthost"}


def _is_deny_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if IP should be denied per 05 spec."""
    # Use ipaddress properties plus explicit checks
    # ip.is_global is False for private, reserved, loopback, link-local, multicast, unspecified
    if ip.is_loopback:
        return True
    if ip.is_private:
        return True
    if ip.is_link_local:
        return True
    if ip.is_multicast:
        return True
    if ip.is_unspecified:
        return True
    if ip.is_reserved:
        return True
    # fallback: not global => deny (catches CGNAT 100.64/10 if not private on this Python)
    try:
        if not ip.is_global:
            return True
    except Exception:
        pass
    return False


def _check_hostname_literal(host: str) -> None:
    """If host is literal IP, check denial directly."""
    # Strip brackets for IPv6 like [::1]
    raw = host
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    # Remove zone id %eth0
    if "%" in raw:
        raw = raw.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(raw)
        if _is_deny_ip(ip):
            raise UnsafeUrlError(f"URL resolves to disallowed address: {raw} ({ip})", hint="private/local network targets are intentionally blocked")
    except ValueError:
        # not a literal IP, need DNS
        pass


def _resolve_and_check(host: str) -> None:
    """Resolve hostname via OS resolver and deny if any IP is unsafe.

    Fails closed when DNS resolution cannot establish that the target is
    public — prevents proxy-mediated bypass where a local resolver cannot
    resolve an internal name but a corporate HTTP proxy could.
    """
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeUrlError(
            f"DNS resolution failed for {host!r}: {e}",
            hint="unable to verify target is public — blocked",
        ) from e
    except Exception as e:
        raise UnsafeUrlError(
            f"DNS resolution error for {host!r}: {e}",
            hint="unable to verify target is public — blocked",
        ) from e

    for family, type_, proto, canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        # Remove zone id if present
        if "%" in ip_str:
            ip_str = ip_str.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_deny_ip(ip):
            raise UnsafeUrlError(f"URL resolves to disallowed address: {host} -> {ip_str}", hint="private/local network targets are intentionally blocked")


def validate_url(url_str: str, config: WebXConfig | None = None) -> urllib.parse.ParseResult:
    """Validate URL per security policy. Returns parsed result if allowed, raises UnsafeUrlError otherwise.

    Checks:
    - scheme http/https only
    - no credentials
    - hostname present
    - hostname not in deny list (localhost)
    - literal IP not denied
    - resolved IPs not denied (DNS)
    - searxng endpoint not targeted (via loopback check + explicit host match if config provided)
    """
    if not isinstance(url_str, str) or not url_str.strip():
        raise UnsafeUrlError("URL is empty", hint="provide http:// or https:// URL")

    raw = url_str.strip()

    # Basic scheme check before parsing
    # urlparse will treat bare paths as path, so need to ensure scheme present
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception as e:
        raise UnsafeUrlError(f"Invalid URL: {raw!r}: {e}") from e

    # Allow only http/https
    if parsed.scheme.lower() not in ("http", "https"):
        raise UnsafeUrlError(f"URL scheme must be http or https: {raw!r}", hint="file:, ftp:, data:, javascript: are blocked")

    # Must have netloc/hostname
    if not parsed.netloc:
        raise UnsafeUrlError(f"URL missing host: {raw!r}")

    # Reject credentials
    # parsed.username/password will be set if userinfo present; also check for @ in netloc before hostname?
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"URL with credentials is not allowed: {raw!r}", hint="credential-bearing URLs are blocked")
    # Additional check: if netloc contains '@' but urlparse didn't catch (edge), still deny
    # Example: http://user:pass@example.com -> username present, already caught. But just in case:
    if "@" in parsed.netloc and parsed.hostname and "@" in raw.split(parsed.hostname)[0]:
        # heuristic: if raw contains userinfo pattern before host
        # We already denied via username, so redundant but keep
        raise UnsafeUrlError(f"URL with credentials is not allowed: {raw!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"URL missing hostname: {raw!r}")

    # Normalize host for checks
    host_low = host.lower().rstrip(".")

    # Explicit localhost deny (covers "localhost" variations)
    if host_low in _DENY_HOSTS:
        raise UnsafeUrlError(f"URL host is disallowed: {host!r}", hint="localhost is blocked")

    # Check literal IP denial
    _check_hostname_literal(host)

    # Resolve and check all IPs
    _resolve_and_check(host)

    # Explicit searxng endpoint check if config provided
    if config is not None:
        try:
            cfg_host = urllib.parse.urlparse(config.searxng_url).hostname
            if cfg_host and host_low == cfg_host.lower():
                raise UnsafeUrlError(f"URL targets local SearXNG endpoint: {raw!r}", hint="local SearXNG is not readable via webx read")
        except UnsafeUrlError:
            raise
        except Exception:
            pass

    # Also check if host is 169.254.169.254 explicitly (link-local metadata) — already covered via is_link_local, but explicit error message
    if host_low == "169.254.169.254":
        raise UnsafeUrlError(f"URL host is disallowed metadata endpoint: {host!r}")

    return parsed


def is_safe_url(url_str: str, config: WebXConfig | None = None) -> bool:
    try:
        validate_url(url_str, config)
        return True
    except UnsafeUrlError:
        return False
