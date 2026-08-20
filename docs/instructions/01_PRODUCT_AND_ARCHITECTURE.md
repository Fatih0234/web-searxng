# 01 — Product and Architecture

## User problem

Coding agents sometimes need fresh external context, but always-on web search creates unnecessary prompt/tool complexity and can encourage excessive browsing. The desired system should make web access **explicit, local, cheap, and disposable**.

## Architecture

```text
                         ┌────────────────────────────┐
                         │ SearXNG                    │
                         │ Docker Compose service     │
                         │ http://127.0.0.1:8888      │
                         │ normally stopped           │
                         └──────────────┬─────────────┘
                                        │
                                  JSON Search API
                                        │
                      ┌─────────────────▼────────────────┐
                      │ webx Python core                 │
                      │                                  │
                      │ SearxngClient.search()           │
                      │ WebReader.read()                 │
                      │ RuntimeManager.ensure_running()  │
                      │ URL/network validation           │
                      └───────────────┬──────────────────┘
                                      │
                    ┌─────────────────┴────────────────┐
                    │                                  │
              CLI frontend                       MCP frontend
              `webx ...`                         `webx-mcp`
                    │                                  │
              shell-capable                      MCP-capable
              coding agent                       exploration agent
```

## Separation of concerns

### `lifecycle.py`

Own Docker Compose interactions and readiness checks. It must not know agent/MCP semantics.

### `searxng.py`

Own the SearXNG HTTP API and normalize search output. It asks `RuntimeManager` to ensure the service is running before a search.

### `security.py`

Own URL parsing, hostname/IP checks, redirect validation, and private-network denial logic.

### `reader.py`

Own controlled page fetching, response-size/type checks, extraction, truncation, and reader metadata. It never starts SearXNG.

### `cli.py`

Argument parsing, stdout/stderr behavior, exit codes. Thin adapter only.

### `mcp_server.py`

Tool schemas/descriptions and process lifecycle. Calls the same core APIs.

## Runtime files

Package safe templates as Python package data:

```text
src/webx/assets/compose.yml
src/webx/assets/settings.yml
```

`webx init` materializes them to an OS-appropriate user data directory determined by `platformdirs`, for example:

- macOS: user Application Support directory for `webx`.
- Linux: XDG user data directory for `webx`.
- Windows: local app-data directory if supported.

Do not rely on the current working directory after installation.

The runtime directory contains something equivalent to:

```text
<user-data>/webx/
├── compose.yml
├── settings.yml
├── .env
└── cache/              # optional SearXNG persistent/cache mount
```

The `.env` contains a locally generated SearXNG secret and must have restrictive permissions where supported.

## Core public Python API

Keep a small API that both frontends can call:

```python
class WebX:
    def search(...)->SearchResponse: ...
    def read(...)->ReadResponse: ...
    def start_search_service()->RuntimeStatus: ...
    def stop_search_service()->RuntimeStatus: ...
    def status()->RuntimeStatus: ...
    def doctor()->DoctorReport: ...
```

Exact class names may differ, but preserve the shape and separation.

## Search flow

```text
webx search
   │
   ├─ validate CLI args
   ├─ RuntimeManager.ensure_running()
   │    ├─ probe 127.0.0.1:8888
   │    ├─ if already healthy: continue
   │    └─ else docker compose up -d + poll readiness
   │
   ├─ SearXNG GET /search?format=json...
   ├─ normalize/dedupe
   ├─ client-side limit
   └─ JSON stdout
```

## Read flow

```text
webx read URL
   │
   ├─ parse + validate scheme
   ├─ resolve hostname; deny unsafe address classes
   ├─ controlled streaming GET
   ├─ validate every redirect target
   ├─ enforce timeout/size/content-type limits
   ├─ Trafilatura extraction for HTML
   ├─ text fallback where appropriate
   ├─ truncate to requested max chars
   └─ Markdown or JSON stdout
```

## Lifecycle policy

### CLI mode

- First `search` lazily starts SearXNG if needed.
- Subsequent searches reuse it.
- `read` does not require/start SearXNG.
- User/agent runs `webx stop` after research.
- `webx stop` uses `docker compose stop`, preserving the container for a fast next startup.
- A maintenance/remove command may use `docker compose down`, but that is not normal session shutdown.

### MCP mode

- Launching `webx-mcp` does not start SearXNG.
- Record whether SearXNG was already running when the MCP process first needs search.
- If MCP caused the stopped service to start, mark it as process-owned for shutdown purposes.
- On normal process shutdown, stop SearXNG **only if this MCP process started it**, unless configured to keep it running.
- If it was already running, never stop it automatically.

This simple ownership rule is sufficient for v1. If future deployments run multiple independent MCP server processes simultaneously, add an inter-process lease/ref-count mechanism rather than guessing.
