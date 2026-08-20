{
  "id": "efebf551",
  "title": "Phase 7 — MCP adapter (stdio, web_search/web_read, ownership)",
  "tags": [
    "phase-7",
    "mcp"
  ],
  "status": "done",
  "created_at": "2026-08-20T09:24:01.457Z"
}

**Goal:** Thin stdio adapter over same core; only 2 tools; lazy-start ownership rule.

**File:** `src/webx/mcp_server.py` (entry point webx-mcp, uses mcp>=2 SDK)

**Requirements (02 Phase7 + 06):**
- stdio transport only, no http/daemon/auth/listener
- expose exactly web_search + web_read, no lifecycle tools
- schemas: web_search(query, limit=8, category=general, language, page, time_range, safe_search); web_read(url, max_chars=40000, include_links, include_tables)
- tool descriptions must include: local SearXNG, snippets candidates not facts, read before relying, multiple queries may be needed, untrusted data boundary, JS/auth pages may not work
- lazy-start: server launch does NOT start SearXNG; first web_search probes; if stopped start and set started_by_mcp=True; if already running set False; web_read never starts SearXNG
- shutdown: on clean exit, if started_by_mcp && WEBX_MCP_STOP_ON_EXIT (default true) then core stop(); else leave running; handle signals best-effort; process-local lock for concurrent first searches

**Tests (07 MCP tests):**
- in-memory client or Inspector: tool list == 2
- launch leaves SearXNG stopped
- web_search invokes core.search
- web_read invokes core.read, leaves SearXNG stopped
- shutdown only stops when MCP started it vs when pre-running
- error mapping: typed exceptions → concise tool errors, no tracebacks

**Validation:** MCP Inspector flow; web_read example.com while stopped; first search starts; multiple searches reuse; terminate leaves/cleans correctly.

Spec refs: 01 Lifecycle MCP policy, 02 Phase7, 06 full, 07 MCP acceptance
