# 09 — Decisions, Tradeoffs, and Future Extensions

## Why not make SearXNG the direct agent tool?

Because infrastructure details should not leak into agent prompts/tool schemas. `webx` creates a stable contract even if the search backend changes later.

Future backend adapters could include Brave, Tavily, Linkup, or another provider without changing the agent-facing `web_search` schema.

## Why search and read are separate?

Search snippets are discovery hints, not sufficient evidence for many claims. Separating `search` from `read` forces a useful research distinction and avoids downloading every result automatically.

## Why no research/answer endpoint?

The coding agent is already the reasoning engine. Adding a WebX LLM layer would duplicate orchestration, add model dependencies, complicate citations, and make behavior harder to audit.

## Why Docker for SearXNG?

It isolates SearXNG's deployment dependencies and makes start/stop predictable. The container can remain stopped most of the time.

## Why omit Valkey?

The official SearXNG limiter requires Valkey, but the documented public-instance features are not needed for local usage. Because WebX binds SearXNG to loopback only, v1 intentionally disables the limiter and omits Valkey. If the service is ever exposed beyond localhost, this decision must be revisited before exposure.

## Why own the HTTP fetch instead of `trafilatura.fetch_url()`?

The URL comes from an AI agent. WebX needs to enforce private-network denial, redirect validation, body-size caps, content-type policy, and predictable timeouts before extraction. Trafilatura remains the content extractor, not the security boundary.

## Why no browser in v1?

A browser adds a large dependency/runtime footprint and creates a much larger interaction/security surface. Most coding research is served well by search + normal HTTP extraction. Add browser rendering only if actual usage demonstrates a meaningful failure rate.

## Why no automatic idle daemon initially?

Explicit `webx stop` and MCP stop-on-exit solve the main resource problem with almost no background machinery. A permanent idle monitor would ironically add another always-running process.

## Candidate v2 extensions, in priority order

Only add these in response to observed need:

1. **Idle timeout without permanent daemon** — perhaps session wrapper or OS-scheduled cleanup, not a busy poller.
2. **PDF reader adapter** — safe download + local text extraction (separate from Trafilatura).
3. **Optional JS renderer** — explicit `web_read_rendered`, not automatic fallback.
4. **Search backend interface** — allow hosted API fallback behind the same schema.
5. **Small ephemeral cache** — reduce duplicate page reads during one research session.
6. **Inter-process runtime lease** — if multiple independent MCP processes become common.
7. **Engine presets** — coding/news/science profiles based on actual SearXNG behavior.
8. **Domain include/exclude filters** — implemented carefully, not as a security substitute.

## Explicit non-goals unless requirements change

- autonomous crawler;
- recursively following links;
- browser login automation;
- stealth scraping/CAPTCHA bypass;
- proxy rotation;
- distributed search infrastructure;
- public multi-user SearXNG hosting;
- long-term web corpus storage;
- automatically executing commands found in webpages.

## Backend portability rule

Agent-facing interfaces should use WebX concepts, never SearXNG-specific field names when avoidable. This is the most important future-proofing choice in the design.
