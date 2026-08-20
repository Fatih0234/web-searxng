"""SearXNG API client — JSON search, normalization, dedupe, client-side limit."""

from __future__ import annotations

import urllib.parse

import httpx

from .config import WebXConfig
from .errors import SearxngSearchError
from .lifecycle import ensure_running
from .models import SearchMeta, SearchQuery, SearchResponse, SearchResult


def _canonical_url(url: str) -> str:
    """Canonicalize for dedupe: lower scheme/host, strip fragment, strip trailing slash."""
    try:
        u = urllib.parse.urlparse(url.strip())
        scheme = u.scheme.lower()
        netloc = u.netloc.lower()
        # remove default ports
        if scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        if scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]
        path = u.path or ""
        # strip trailing slash for dedupe but keep root empty
        # keep query as is
        canonical = urllib.parse.urlunparse((scheme, netloc, path.rstrip("/"), "", u.query, ""))
        return canonical
    except Exception:
        return url.strip().split("#")[0].rstrip("/")


def normalize_results(raw: dict, query: SearchQuery) -> SearchResponse:
    """Normalize raw SearXNG JSON to SearchResponse. Tolerant to missing fields."""
    if not isinstance(raw, dict):
        raise SearxngSearchError(f"Unexpected SearXNG response type: {type(raw).__name__}")

    raw_results = raw.get("results")
    if raw_results is None:
        # some responses may use 'results' or empty
        raw_results = []
    if not isinstance(raw_results, list):
        raise SearxngSearchError(f"Unexpected SearXNG results type: {type(raw_results).__name__}")

    seen: dict[str, SearchResult] = {}
    ordered: list[SearchResult] = []

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link") or ""
        if not url or not isinstance(url, str):
            continue
        url = url.strip()
        if not url:
            continue

        title = item.get("title") or ""
        if not isinstance(title, str):
            title = str(title)
        snippet = item.get("content") or item.get("snippet") or item.get("abstract") or ""
        if not isinstance(snippet, str):
            snippet = str(snippet)

        engines = item.get("engines") or item.get("engine") or []
        if isinstance(engines, str):
            engines = [engines]
        elif not isinstance(engines, list):
            engines = [str(engines)]
        # ensure list of str
        engines = [str(e) for e in engines if e]

        try:
            score = float(item.get("score", 0.0) or 0.0)
        except Exception:
            score = 0.0

        category = item.get("category") or query.category or "general"
        if not isinstance(category, str):
            category = str(category)

        published = item.get("publishedDate") or item.get("published_date") or item.get("published") or None
        if published is not None and not isinstance(published, str):
            published = str(published)

        result = SearchResult(
            title=title.strip(),
            url=url,
            snippet=snippet.strip(),
            engines=engines,
            score=score,
            category=category,
            published_date=published,
        )

        canon = _canonical_url(url)
        if canon not in seen:
            seen[canon] = result
            ordered.append(result)
        else:
            # keep highest-ranked (first occurrence) — ignore duplicate
            continue

    # client-side limit (preserve ranking order)
    limit = query.limit if query.limit else 8
    if limit > 50:
        limit = 50
    limited = ordered[:limit]

    meta = SearchMeta(
        result_count=len(limited),
        page=query.page,
        category=query.category or "general",
        time_range=query.time_range,
    )

    return SearchResponse(query=query.query, results=limited, meta=meta)


class SearxngClient:
    def __init__(self, config: WebXConfig) -> None:
        self.config = config

    def search(
        self,
        query: str,
        limit: int = 8,
        category: str | None = "general",
        language: str | None = None,
        page: int = 1,
        time_range: str | None = None,
        safe_search: int | None = None,
        engines: list[str] | None = None,
    ) -> SearchResponse:
        q = SearchQuery(
            query=query,
            limit=limit,
            category=category,
            language=language,
            page=page,
            time_range=time_range,
            safe_search=safe_search,
            engines=engines,
        )

        # Validate time_range
        if time_range is not None and time_range not in ("day", "month", "year"):
            raise SearxngSearchError(f"Invalid time_range: {time_range!r}")

        if safe_search is not None and safe_search not in (0, 1, 2):
            raise SearxngSearchError(f"Invalid safe_search: {safe_search!r}")

        # ensure SearXNG running (lazy start)
        ensure_running(self.config)

        # Build params per SearXNG docs
        params: dict[str, str] = {
            "q": query,
            "format": "json",
        }
        if category:
            params["categories"] = category
        if language:
            params["language"] = language
        if page and page != 1:
            params["pageno"] = str(page)
        if time_range:
            params["time_range"] = time_range
        if safe_search is not None:
            params["safesearch"] = str(safe_search)
        if engines:
            # passthrough as comma-joined
            params["engines"] = ",".join(engines)

        url = self.config.searxng_url.rstrip("/") + "/search"

        try:
            with httpx.Client(timeout=self.config.search_timeout, follow_redirects=False, trust_env=False) as client:
                resp = client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.TimeoutException as e:
            raise SearxngSearchError(f"SearXNG search timeout: {e}") from e
        except httpx.RequestError as e:
            raise SearxngSearchError(f"SearXNG request failed: {e}") from e

        if resp.status_code != 200:
            body = resp.text[:2000]
            raise SearxngSearchError(f"SearXNG search failed HTTP {resp.status_code}: {body}")

        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            # SearXNG should return json when format=json; if not, try parse anyway
            pass

        try:
            data = resp.json()
        except Exception as e:
            raise SearxngSearchError(f"SearXNG invalid JSON: {e}; body: {resp.text[:2000]}") from e

        return normalize_results(data, q)


def search_with_config(
    config: WebXConfig,
    query: str,
    limit: int = 8,
    category: str | None = "general",
    language: str | None = None,
    page: int = 1,
    time_range: str | None = None,
    safe_search: int | None = None,
    engines: list[str] | None = None,
) -> SearchResponse:
    client = SearxngClient(config)
    return client.search(query, limit, category, language, page, time_range, safe_search, engines)
