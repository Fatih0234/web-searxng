"""WebReader — controlled fetch + Trafilatura extraction, per 05 spec."""

from __future__ import annotations

import concurrent.futures
import time
import urllib.parse

import httpx

from . import __version__
from .config import WebXConfig
from .errors import ExtractionError, FetchError, UnsupportedContentTypeError, UnsafeUrlError
from .models import ReadResponse
from .security import validate_url

_MAX_REDIRECTS = 5

_ALLOWED_PREFIXES = ("text/",)
_ALLOWED_EXACT = {
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/json",
    "application/ld+json",
    "application/javascript",
    "application/x-javascript",
}


def _is_allowed_content_type(ct: str) -> bool:
    if not ct:
        return True
    ct = ct.split(";")[0].strip().lower()
    if not ct:
        return True
    if ct.startswith(_ALLOWED_PREFIXES):
        return True
    if ct in _ALLOWED_EXACT:
        return True
    if ct.endswith("+xml") or ct.endswith("+json"):
        return True
    if "html" in ct:
        return True
    return False


def _get_user_agent() -> str:
    return f"webx/{__version__} local-research-tool"


def _truncate(content: str, max_chars: int) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False
    cut = max_chars
    window_start = max(0, max_chars - 500)
    window = content[window_start:max_chars]
    for sep in ("\n\n", "\n", ". ", " "):
        idx = window.rfind(sep)
        if idx != -1 and idx > 50:
            cut = window_start + idx + len(sep)
            break
    truncated = content[:cut].rstrip()
    return truncated, True


class WebReader:
    def __init__(self, config: WebXConfig) -> None:
        self.config = config

    def read(
        self,
        url: str,
        max_chars: int | None = None,
        include_links: bool = False,
        include_tables: bool = True,
        precision: bool = False,
        recall: bool = False,
    ) -> ReadResponse:
        if max_chars is None:
            max_chars = self.config.max_read_chars
        if max_chars < 1000 or max_chars > 500000:
            raise FetchError(f"max_chars out of range: {max_chars}")

        current_url = url
        visited: set[str] = set()
        final_url: str | None = None
        final_content_type: str | None = None
        final_content_type_full: str | None = None
        body_bytes: bytes | None = None
        # Absolute wall-clock deadline for the entire fetch (redirects + body).
        # httpx read timeout is per-chunk; this deadline bounds total time.
        deadline = time.monotonic() + self.config.read_timeout

        for _ in range(_MAX_REDIRECTS + 1):
            # Check overall deadline before each hop
            remaining_overall = deadline - time.monotonic()
            if remaining_overall <= 0:
                raise FetchError(f"Overall read timeout {self.config.read_timeout}s exceeded for {url}")
            # Validate every hop
            validate_url(current_url, self.config)

            # Remaining time bounds all network waits for this hop
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError(f"Overall read timeout {self.config.read_timeout}s exceeded for {current_url}")
            timeout = httpx.Timeout(
                connect=min(5.0, remaining),
                read=remaining,
                write=min(5.0, remaining),
                pool=min(5.0, remaining),
            )
            headers = {
                "User-Agent": _get_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
            }

            redirect_next: str | None = None

            try:
                with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                    with client.stream("GET", current_url, headers=headers) as resp:
                        # Redirect handling
                        if resp.status_code in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location")
                            if not location:
                                raise FetchError(f"Redirect {resp.status_code} without Location from {current_url}")
                            next_url = urllib.parse.urljoin(current_url, location)
                            if next_url in visited or next_url == current_url:
                                raise FetchError(f"Redirect loop detected: {current_url} -> {next_url}")
                            if len(visited) >= _MAX_REDIRECTS:
                                raise FetchError(f"Too many redirects (> {_MAX_REDIRECTS}) starting from {url}")
                            try:
                                validate_url(next_url, self.config)
                            except UnsafeUrlError as e:
                                raise UnsafeUrlError(f"Redirect target disallowed: {next_url!r} from {current_url!r}: {e}") from e
                            redirect_next = next_url
                        else:
                            if resp.status_code < 200 or resp.status_code >= 400:
                                raise FetchError(f"HTTP {resp.status_code} fetching {current_url}")
                            ct = resp.headers.get("content-type", "")
                            ct_main = ct.split(";")[0].strip().lower() if ct else ""
                            if not _is_allowed_content_type(ct_main):
                                raise UnsupportedContentTypeError(
                                    f"Unsupported content type: {ct_main or 'unknown'} for {current_url}",
                                    hint="binary types like PDF/image are not supported in v1",
                                )
                            # Content-Length pre-check
                            cl = resp.headers.get("content-length")
                            if cl is not None:
                                try:
                                    cl_int = int(cl)
                                    if cl_int > self.config.max_response_bytes:
                                        raise FetchError(f"Content-Length {cl_int} exceeds limit {self.config.max_response_bytes} for {current_url}")
                                except ValueError:
                                    pass
                            # Stream body with absolute deadline — next blocking read
                            # is constrained by remaining time, not just inactivity.
                            buf = bytearray()
                            total = 0
                            # Deadline-aware chunk iteration
                            iterator = iter(resp.iter_bytes(chunk_size=8192))
                            sentinel = object()
                            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                            _timed_out = False
                            try:
                                while True:
                                    remaining_chunk = deadline - time.monotonic()
                                    if remaining_chunk <= 0:
                                        raise FetchError(
                                            f"Overall read timeout {self.config.read_timeout}s exceeded while fetching {current_url}"
                                        )
                                    future = _executor.submit(next, iterator, sentinel)
                                    try:
                                        chunk = future.result(timeout=remaining_chunk)
                                    except concurrent.futures.TimeoutError as e:
                                        _timed_out = True
                                        try:
                                            resp.close()
                                        except Exception:
                                            pass
                                        _executor.shutdown(wait=False, cancel_futures=True)
                                        raise FetchError(
                                            f"Overall read timeout {self.config.read_timeout}s exceeded while fetching {current_url}"
                                        ) from e
                                    if chunk is sentinel:
                                        break
                                    if not chunk:
                                        continue
                                    total += len(chunk)
                                    if total > self.config.max_response_bytes:
                                        raise FetchError(
                                            f"Response body exceeds limit {self.config.max_response_bytes} bytes for {current_url}"
                                        )
                                    buf.extend(chunk)
                                    if time.monotonic() > deadline:
                                        raise FetchError(
                                            f"Overall read timeout {self.config.read_timeout}s exceeded while fetching {current_url}"
                                        )
                            finally:
                                if not _timed_out:
                                    _executor.shutdown(wait=True)
                            body_bytes = bytes(buf)
                            final_url = current_url
                            final_content_type = ct_main or ct
                            final_content_type_full = ct
                            # success - no redirect
                            redirect_next = None
            except (UnsupportedContentTypeError, UnsafeUrlError, FetchError):
                raise
            except httpx.TimeoutException as e:
                raise FetchError(f"Timeout fetching {current_url}: {e}") from e
            except httpx.RequestError as e:
                raise FetchError(f"Request failed fetching {current_url}: {e}") from e

            if redirect_next is not None:
                visited.add(current_url)
                current_url = redirect_next
                # continue loop for next hop, body_bytes stays None
                continue
            else:
                # success
                if body_bytes is not None and final_url is not None:
                    break
                # if we got here without redirect but also without body, it's unexpected
                raise FetchError(f"Fetch did not return body for {current_url}")
        else:
            raise FetchError(f"Too many redirects (> {_MAX_REDIRECTS}) starting from {url}")

        assert body_bytes is not None and final_url is not None
        # Decode — keep full Content-Type for charset, not the stripped MIME.
        encoding = "utf-8"
        ct_for_charset = final_content_type_full or ""
        if "charset=" in ct_for_charset.lower():
            try:
                for part in ct_for_charset.split(";"):
                    if "charset=" in part.lower():
                        encoding = part.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            except Exception:
                encoding = "utf-8"

        try:
            text = body_bytes.decode(encoding, errors="replace")
        except Exception:
            text = body_bytes.decode("utf-8", errors="replace")

        ct_low = (final_content_type or "").lower()
        # Decide whether to use trafilatura
        use_trafilatura = False
        if not ct_low or "html" in ct_low or "xml" in ct_low:
            use_trafilatura = True
        elif ct_low.startswith("text/"):
            # for text/*, check if it looks like html anyway
            if text.lstrip().lower().startswith(("<!doctype html", "<html")):
                use_trafilatura = True
            else:
                use_trafilatura = False
        else:
            use_trafilatura = False

        extracted: str | None = None
        title: str | None = None
        engine: str | None = None

        if use_trafilatura:
            try:
                import trafilatura

                extracted = trafilatura.extract(
                    text,
                    url=final_url,
                    output_format="markdown",
                    include_comments=False,
                    include_tables=include_tables,
                    include_links=include_links,
                    with_metadata=False,
                    favor_precision=precision,
                    favor_recall=recall,
                )
                engine = "trafilatura"
                if not extracted or not extracted.strip():
                    try:
                        fallback = trafilatura.html2txt(text)  # type: ignore[attr-defined]
                    except Exception:
                        fallback = None
                    if fallback and fallback.strip():
                        extracted = fallback
                        engine = "trafilatura-fallback"
                    else:
                        # Both extractors failed — do not flood context with raw HTML.
                        # For HTML/XML we fail; raw passthrough is only for non-HTML text.
                        raise ExtractionError(
                            f"Extraction returned empty for {final_url}",
                            hint="page may be JS-rendered or empty",
                        )
                try:
                    from trafilatura import extract_metadata

                    meta = extract_metadata(text, url=final_url)
                    if meta and getattr(meta, "title", None):
                        title = meta.title
                except Exception:
                    title = None
            except ExtractionError:
                raise
            except Exception as e:
                raise ExtractionError(f"Extraction failed for {final_url}: {e}") from e
        else:
            extracted = text
            engine = "raw"
            title = None

        if extracted is None:
            raise ExtractionError(f"Extraction returned None for {final_url}")

        extracted = extracted.strip()
        if not extracted:
            raise ExtractionError(f"Extraction returned empty for {final_url}", hint="page may be JS-only or require rendering (not supported in v1)")

        truncated_content, truncated = _truncate(extracted, max_chars)

        return ReadResponse(
            url=url,
            final_url=final_url,
            title=title,
            content_type=final_content_type,
            content=truncated_content,
            truncated=truncated,
            characters=len(truncated_content),
            engine=engine,
        )
