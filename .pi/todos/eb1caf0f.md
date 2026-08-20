{
  "id": "eb1caf0f",
  "title": "Phase 4 — SearXNG search client + CLI search",
  "tags": [
    "phase-4",
    "search"
  ],
  "status": "done",
  "created_at": "2026-08-20T09:23:46.425Z"
}

**Goal:** JSON API search, normalize/dedupe, client-side limit, lifecycle noise never on stdout.

**File:** `src/webx/searxng.py` (SearxngClient)

**API:** `search(query, limit=8, category="general", language=None, page=1, time_range=None, safe_search=None, engines=None) -> SearchResponse`

**Mapping to SearXNG GET /search:** `q`, `format=json`, `categories`, `language`, `pageno`, `time_range`, `safesearch`, `engines` passthrough. Use httpx, timeout WEBX_SEARCH_TIMEOUT.

**Normalization (02 Phase4 + 04 + 03 envelope):**
- tolerant to missing optional fields per engine
- shape {title, url, snippet, engines[], score, category, published_date}
- dedupe by canonicalized URL (lowercase, strip trailing slash/fragment) keep highest-ranked occurrence
- apply limit client-side (hard cap ~50, default 8)
- envelope {query, results[], meta{result_count, page, category, time_range}}

**Dependencies:** calls RuntimeManager.ensure_running() before HTTP.

**Tests:** Fixture JSON; missing fields tolerated; dedupe; limit; malformed response typed error; params sent correctly; lifecycle stderr not stdout.

**CLI partial:** `webx search QUERY --limit --category --language --page --time --safe-search --engine --pretty` wired but without reader yet; stdout valid JSON, stderr diagnostics.

**Validation:** `webx search "SearXNG documentation" --limit 5 --pretty` returns stable JSON, second search reuses container.

Spec refs: 02 Phase4, 03 search spec, 04 API, 07 Search normalization tests
