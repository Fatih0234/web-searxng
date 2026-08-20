"""WebReader — controlled fetch + Trafilatura extraction, per 05 spec."""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import sys
import time
import urllib.parse

import httpx

from . import __version__
from .config import WebXConfig
from .errors import ExtractionError, FetchError, UnsupportedContentTypeError, UnsafeUrlError
from .models import ReadResponse
from .security import resolve_and_check, validate_url

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
    if ct == "application/pdf":
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


# In-memory LRU cache for reads (per process, TTL 5min, max 20 entries)
_READ_CACHE: dict[str, tuple[float, ReadResponse]] = {}
_READ_CACHE_TTL = 300.0
_READ_CACHE_MAX = 20


def _cache_key(url: str, max_chars: int, include_links: bool, include_tables: bool, precision: bool, recall: bool) -> str:
    raw = f"{url}|{max_chars}|{include_links}|{include_tables}|{precision}|{recall}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _pdf_extract_worker(args: tuple[bytes, int]) -> tuple[str, int, int]:
    """Worker for PDF extraction in isolated process — must be top-level for pickling."""
    data, max_chars = args
    import pypdf  # type: ignore

    reader = pypdf.PdfReader(io.BytesIO(data))
    pages_total = len(reader.pages)
    pages_read = min(pages_total, 20)
    texts: list[str] = []
    for page in reader.pages[:20]:
        try:
            t = page.extract_text() or ""
            texts.append(t)
            if sum(len(x) for x in texts) > max_chars + 5000:
                break
        except Exception:
            continue
    extracted = "\n\n".join(texts).strip()
    return extracted, pages_total, pages_read


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
        no_cache: bool = False,
    ) -> ReadResponse:
        if max_chars is None:
            max_chars = self.config.max_read_chars
        if max_chars < 1000 or max_chars > 500000:
            raise FetchError(f"max_chars out of range: {max_chars}")

        # Cache check (per-process, TTL)
        cache_key = _cache_key(url, max_chars, include_links, include_tables, precision, recall)
        if not no_cache:
            cached = _READ_CACHE.get(cache_key)
            if cached and (time.monotonic() - cached[0] < _READ_CACHE_TTL):
                return cached[1]

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

            # DNS pinning — resolve once, pin to validated IPs (fail-closed, http+https).
            # For https, preserve SNI via extensions={"sni_hostname": original_host}.
            _parsed_pin = urllib.parse.urlparse(current_url)
            _scheme = _parsed_pin.scheme.lower()
            _hostname = _parsed_pin.hostname
            _is_literal = False
            if _hostname:
                try:
                    import ipaddress as _ipaddr_pin  # noqa: F401

                    _ipaddr_pin.ip_address(_hostname.strip("[]"))
                    _is_literal = True
                except ValueError:
                    _is_literal = False
                except Exception:
                    _is_literal = False
            _pinned_ips: list[str] | None = None
            if _hostname and not _is_literal and _scheme in ("http", "https"):
                # Fail-closed: any deny → UnsafeUrlError; any other pinning error → FetchError (no fallback)
                try:
                    _pinned_ips = resolve_and_check(_hostname)
                except UnsafeUrlError:
                    raise
                except Exception as e:
                    raise FetchError(f"DNS pinning failed for {_hostname}: {e}") from e
            # Build candidates — one per validated IP, try each on ConnectError
            _candidates: list[tuple[str, dict[str, str], dict | None]] = []
            if _pinned_ips is None:
                _candidates = [(current_url, {}, None)]
            else:
                for _ip in _pinned_ips:
                    _host = f"[{_ip}]" if ":" in _ip and not _ip.startswith("[") else _ip
                    _port = f":{_parsed_pin.port}" if _parsed_pin.port else ""
                    _path = _parsed_pin.path or "/"
                    _query = f"?{_parsed_pin.query}" if _parsed_pin.query else ""
                    _frag = f"#{_parsed_pin.fragment}" if _parsed_pin.fragment else ""
                    _pinned_url = f"{_scheme}://{_host}{_port}{_path}{_query}{_frag}"
                    _pin_headers = {"Host": _hostname if not _parsed_pin.port else f"{_hostname}:{_parsed_pin.port}"}
                    _pin_ext = {"sni_hostname": _hostname} if _scheme == "https" else None
                    _candidates.append((_pinned_url, _pin_headers, _pin_ext))

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
            base_headers = {
                "User-Agent": _get_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
            }

            redirect_next: str | None = None
            _last_connect_error: Exception | None = None
            _hop_success = False
            for _cand_idx, (_pinned_url, _pin_headers, _pin_ext) in enumerate(_candidates):
                headers = {**base_headers, **_pin_headers}
                try:
                    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                        with client.stream("GET", _pinned_url, headers=headers, extensions=_pin_ext) as resp:
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
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # type: ignore[attr-defined]
                    _last_connect_error = e
                    if _cand_idx < len(_candidates) - 1:
                        continue
                    raise FetchError(f"Connection failed for {current_url} (tried {len(_candidates)} pinned IPs): {e}") from e
                except httpx.TimeoutException as e:
                    raise FetchError(f"Timeout fetching {current_url}: {e}") from e
                except httpx.RequestError as e:
                    raise FetchError(f"Request failed fetching {current_url}: {e}") from e
                # Success for this candidate (either redirect or body)
                _hop_success = True
                break
            if not _hop_success:
                if _last_connect_error is not None:
                    raise FetchError(f"Connection failed for {current_url}: {_last_connect_error}") from _last_connect_error
                # No candidate succeeded but no exception – should be unreachable
                raise FetchError(f"Fetch failed for {current_url} (no pinned candidate succeeded)")

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
        # PDF branch — extract via pypdf in isolated subprocess (10 MiB already enforced, limit 20 pages)
        _ct_low_pdf = (final_content_type or "").lower().split(";")[0].strip()
        if _ct_low_pdf == "application/pdf":
            try:
                import pypdf  # type: ignore  # noqa: F401
            except ImportError as e:
                raise UnsupportedContentTypeError(
                    f"PDF support not installed for {final_url} — install with `pip install -e \".[pdf]\"` or `uv sync --extra pdf`",
                    hint="PDF reader is optional",
                ) from e
            try:
                # Isolate parser in subprocess with wall-clock limit (prevent OOM/CPU in main process)
                _extracted_pdf: str | None = None
                _pages_total: int | None = None
                _pages_read: int | None = None
                try:
                    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as _pool:
                        _future = _pool.submit(_pdf_extract_worker, (body_bytes, max_chars))
                        _extracted_pdf, _pages_total, _pages_read = _future.result(timeout=10)
                except concurrent.futures.TimeoutError as e:
                    raise ExtractionError(f"PDF extraction timed out for {final_url} (10s)", hint="large or malformed PDF") from e
                except Exception as e:
                    # Fallback: try in-process for environments where fork is restricted (e.g., some CI)
                    # Only fallback if the process pool itself failed to start, not for PDF parse errors
                    if "cannot pickle" in str(type(e)).lower() or "process" in str(e).lower():
                        try:
                            _extracted_pdf, _pages_total, _pages_read = _pdf_extract_worker((body_bytes, max_chars))
                        except Exception as ie:
                            raise ExtractionError(f"PDF extraction failed for {final_url}: {ie}") from ie
                    else:
                        raise ExtractionError(f"PDF extraction failed for {final_url}: {e}") from e
                if _extracted_pdf is None or not _extracted_pdf.strip():
                    raise ExtractionError(f"PDF extraction returned empty for {final_url}", hint="scanned PDF may be image-only (OCR required)")
                truncated_pdf, truncated_flag_pdf = _truncate(_extracted_pdf, max_chars)
                # Partial if page limit hit or char limit hit
                _is_partial = False
                _partial_reason: str | None = None
                if _pages_total is not None and _pages_read is not None and _pages_total > _pages_read:
                    _is_partial = True
                    _partial_reason = "page_limit"
                    truncated_flag_pdf = True
                if truncated_flag_pdf and not _is_partial:
                    _is_partial = True
                    _partial_reason = "char_limit"
                resp_pdf = ReadResponse(
                    url=url,
                    final_url=final_url,
                    title=None,
                    content_type=final_content_type,
                    content=truncated_pdf,
                    truncated=truncated_flag_pdf,
                    characters=len(truncated_pdf),
                    engine="pypdf",
                    pages_total=_pages_total,
                    pages_read=_pages_read,
                    partial=_is_partial,
                    partial_reason=_partial_reason,
                )
                if not no_cache:
                    if len(_READ_CACHE) >= _READ_CACHE_MAX:
                        oldest = min(_READ_CACHE, key=lambda k: _READ_CACHE[k][0])
                        _READ_CACHE.pop(oldest, None)
                    _READ_CACHE[cache_key] = (time.monotonic(), resp_pdf)
                return resp_pdf
            except (ExtractionError, UnsupportedContentTypeError):
                raise
            except Exception as e:
                raise ExtractionError(f"PDF extraction failed for {final_url}: {e}") from e
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

        resp = ReadResponse(
            url=url,
            final_url=final_url,
            title=title,
            content_type=final_content_type,
            content=truncated_content,
            truncated=truncated,
            characters=len(truncated_content),
            engine=engine,
        )
        if not no_cache:
            if len(_READ_CACHE) >= _READ_CACHE_MAX:
                oldest = min(_READ_CACHE, key=lambda k: _READ_CACHE[k][0])
                _READ_CACHE.pop(oldest, None)
            _READ_CACHE[cache_key] = (time.monotonic(), resp)
        return resp
