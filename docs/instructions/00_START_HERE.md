# 00 — Start Here

## Mission

Build a local utility that lets a user selectively grant coding agents web access without permanently bloating the agent's system prompt or tool set.

The user has two modes:

### Mode A — Minimal coding agent

Normally the agent has no web tool. When external/current context is useful, the user adds a short task-level prompt authorizing shell use of:

```bash
webx search "query"
webx read "https://..."
```

The agent can perform several searches and reads, then call:

```bash
webx stop
```

The base agent configuration remains unchanged.

### Mode B — Exploration/multi-agent system

A larger coding agent already supports MCP/sub-agents and may always have a web tool schema available. It connects to `webx-mcp`, which exposes exactly:

- `web_search`
- `web_read`

Launching the MCP server must consume essentially no SearXNG compute. SearXNG starts only when `web_search` is first used.

## Product philosophy

WebX is **not a research agent**. It is two primitives plus lifecycle management:

```text
search(query) -> ranked URLs/snippets
read(url)     -> cleaned page content
```

The coding agent itself decides how many searches to run, which sources to read, whether information conflicts, and when research is sufficient.

## Build order

Implement in this order so each layer can be tested before the next:

1. Python package skeleton, errors, models, configuration paths.
2. Runtime template materialization (`webx init`).
3. Docker Compose lifecycle (`up`, lazy `ensure_running`, `stop`, `status`, `doctor`).
4. SearXNG API client and result normalization.
5. CLI `search`.
6. Safe HTTP reader and Trafilatura extraction.
7. CLI `read`.
8. Integration tests against local SearXNG.
9. MCP stdio adapter using the same core.
10. Docs and final end-to-end acceptance tests.

## Important implementation choices already decided

Do not reopen these unless there is a concrete technical blocker:

- Python implementation.
- Docker Compose for SearXNG v1.
- One SearXNG container only for the private laptop setup.
- No reverse proxy.
- No Valkey/Redis in v1 because the service is local-only and SearXNG limiter is disabled.
- JSON output enabled in SearXNG.
- Search server bound to loopback only.
- Direct HTTP page fetch controlled by WebX, then raw content passed to Trafilatura. Do **not** let Trafilatura independently fetch arbitrary URLs because WebX must enforce network safety first.
- No browser/Playwright fallback in v1.
- No LLM summarization inside WebX.
- No page crawling beyond URLs explicitly requested by the agent.
- MCP is stdio only in v1.

## Success criterion

The result should feel like a Unix tool: predictable, composable, easy to inspect, easy to stop, and small enough that the user understands what is running on the laptop.
