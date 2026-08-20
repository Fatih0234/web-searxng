# WebX — Local On-Demand Web Search for Coding Agents

This package is a **build specification and instruction set**, not the finished implementation. Give the whole folder to a coding agent in an empty repository and ask it to implement the project exactly as specified.

## Goal

Build a small local tool named `webx` that gives coding agents web access only when desired:

- **Search:** local SearXNG in Docker, bound only to `127.0.0.1`.
- **Read/scrape:** direct HTTP fetch + Trafilatura main-content extraction.
- **Minimal-agent mode:** shell commands (`webx search`, `webx read`) used only when a temporary prompt authorizes them.
- **Exploration-agent mode:** an optional stdio MCP server exposing only `web_search` and `web_read`.
- **On-demand lifecycle:** SearXNG is normally stopped; the first search lazily starts it. It stays available for the research session, then can be stopped explicitly or by the MCP process if that process started it.

## Recommended reading order for the coding agent

1. `AGENTS.md`
2. `00_START_HERE.md`
3. `01_PRODUCT_AND_ARCHITECTURE.md`
4. `02_BUILD_PLAN.md`
5. `03_CLI_AND_CORE_SPEC.md`
6. `04_SEARXNG_RUNTIME.md`
7. `05_WEB_READER_AND_SECURITY.md`
8. `06_MCP_ADAPTER.md`
9. `07_TEST_AND_ACCEPTANCE.md`
10. `08_OPERATIONS_AND_USAGE.md`
11. `09_DECISIONS_AND_FUTURE.md`
12. `SOURCES.md`

The `prompts/` folder contains copy-paste prompts for agents after `webx` exists. `skills/web-research/SKILL.md` is an optional generic skill template; do not make it a dependency of the core design.

## Core design in one diagram

```text
                    local laptop

      ┌──────────────────────────────────┐
      │ SearXNG container                │
      │ 127.0.0.1:8888                   │
      │ normally STOPPED                 │
      └───────────────┬──────────────────┘
                      │ JSON Search API
                      │
              ┌───────▼────────┐
              │ webx core      │
              │                │
              │ search()       │
              │ read()         │
              │ lifecycle      │
              │ URL security   │
              └──────┬─────┬───┘
                     │     │
           ┌─────────┘     └──────────┐
           │                          │
      `webx` CLI                optional MCP
                                `webx-mcp`
           │                          │
   minimal coding agent       exploration agent
   temporary authorization    persistent tool schema
```

## Non-goals for v1

Do **not** turn this into a browser automation platform, autonomous research framework, crawler, hosted service, search-result summarizer, vector database, or general MCP toolbox. The coding agent itself is the reasoning/orchestration layer. WebX should remain small infrastructure.
