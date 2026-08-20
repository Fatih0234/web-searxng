"""Typed exceptions mapped to CLI exit codes per 03 spec.

Exit codes:
  0 success
  2 invalid CLI usage / validation
  3 local runtime or Docker unavailable
  4 SearXNG search/start failure
  5 unsafe/disallowed URL
  6 page fetch/extraction failure
  7 unsupported response content type
"""

from __future__ import annotations


class WebXError(Exception):
    """Base for all WebX errors."""

    exit_code: int = 1
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint


class UsageError(WebXError):
    exit_code = 2


class RuntimeError(WebXError):  # noqa: A001
    exit_code = 3


class DockerUnavailableError(RuntimeError):
    pass


class SearxngError(WebXError):
    exit_code = 4


class SearxngStartupError(SearxngError):
    pass


class SearxngSearchError(SearxngError):
    pass


class SecurityError(WebXError):
    exit_code = 5


class UnsafeUrlError(SecurityError):
    pass


class FetchError(WebXError):
    exit_code = 6


class ExtractionError(FetchError):
    pass


class UnsupportedContentTypeError(WebXError):
    exit_code = 7


# Map exit_code -> exception for convenience
EXIT_CODE_MAP = {
    2: UsageError,
    3: RuntimeError,
    4: SearxngError,
    5: SecurityError,
    6: FetchError,
    7: UnsupportedContentTypeError,
}
