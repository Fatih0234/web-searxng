# 02 — Build Plan

## Phase 1 — Project foundation

Create a normal `src/` Python package with `pyproject.toml`.

Recommended runtime dependencies:

```text
httpx>=0.28,<1
trafilatura>=2.2,<3
platformdirs>=4,<5
```

Optional MCP dependency:

```text
mcp>=2,<3
```

Development dependencies should include `pytest`, `pytest-cov`, and whichever lightweight formatter/linter the coding agent normally uses. Avoid adding runtime dependencies merely for cosmetic CLI output.

Console scripts:

```toml
[project.scripts]
webx = "webx.cli:main"
webx-mcp = "webx.mcp_server:main"
```

Make package assets (`compose.yml`, `settings.yml`) available through `importlib.resources`.

### Deliverable

`webx --help` runs even before Docker is installed.

---

## Phase 2 — Configuration and runtime materialization

Implement a configuration object that resolves:

- runtime/data directory via `platformdirs`;
- SearXNG base URL, default `http://127.0.0.1:8888`;
- Compose project/runtime path;
- Docker command (`docker` by default);
- startup timeout;
- search timeout;
- reader timeout;
- max response bytes;
- default max extracted characters.

Allow environment overrides with a `WEBX_` prefix, but keep sane defaults. Do not require a config file for normal use.

`webx init` must:

1. create the runtime directory;
2. copy/update packaged safe templates;
3. generate `.env` if absent using `secrets.token_hex(32)`;
4. never overwrite an existing secret without an explicit reset command;
5. print the runtime path and what was created;
6. not start Docker.

Recommended environment variables:

```text
WEBX_DATA_DIR
WEBX_SEARXNG_URL
WEBX_DOCKER_CMD
WEBX_STARTUP_TIMEOUT
WEBX_SEARCH_TIMEOUT
WEBX_READ_TIMEOUT
WEBX_MAX_RESPONSE_BYTES
WEBX_MAX_READ_CHARS
WEBX_MCP_STOP_ON_EXIT
```

### Deliverable

`webx init` is idempotent and testable with a temporary data directory.

---

## Phase 3 — Docker/SearXNG lifecycle

Implement a tiny subprocess adapter. Never concatenate untrusted shell strings; pass argument lists to `subprocess.run`.

Required operations:

```text
compose_up()
compose_stop()
compose_down()       # maintenance, not normal shutdown
compose_ps()
compose_logs()       # optional diagnostic helper
probe_http()
ensure_running()
status()
```

`ensure_running()` algorithm:

1. Probe the configured local SearXNG URL.
2. If healthy, return `already_running=True` without invoking Docker.
3. Ensure runtime templates exist (materialize if safe to do so).
4. Execute `docker compose -f <compose> up -d`.
5. Poll the root URL until healthy or startup timeout expires.
6. On timeout, include recent Compose logs in the error if feasible.

Using `compose up -d` for lazy start is intentional: it works for both first creation and subsequent restarts. Normal shutdown should still use `compose stop` to retain the created container.

### Deliverable

Starting, stopping, and repeated starting are idempotent. No SearXNG process remains active after `webx stop`.

---

## Phase 4 — Search client

Implement SearXNG search through its JSON HTTP API, not by parsing HTML.

Required input fields:

```text
query: str
limit: int = 8
category: str | None = "general"
language: str | None = None
page: int = 1
time_range: "day" | "month" | "year" | None
safe_search: 0 | 1 | 2 | None
engines: list[str] | None      # optional passthrough if implemented cleanly
```

Map these to documented SearXNG parameters. `limit` is a WebX client-side result cap, not assumed to be a SearXNG API parameter.

Normalize each result conservatively. Do not depend on every engine returning the same optional fields.

Recommended normalized shape:

```json
{
  "title": "...",
  "url": "https://...",
  "snippet": "...",
  "engines": ["..."],
  "score": 0.0,
  "category": "general",
  "published_date": null
}
```

Deduplicate by canonicalized URL while preserving the highest-ranked occurrence. Do not over-aggressively rewrite URLs in v1.

### Deliverable

`webx search "query" --limit 5` returns stable JSON and never emits lifecycle log noise to stdout.

---

## Phase 5 — Safe page reader

Implement safe fetching separately from Trafilatura. See `05_WEB_READER_AND_SECURITY.md` in full before coding.

Critical architecture:

```text
URL
 -> WebX validation
 -> WebX HTTP fetch with limits
 -> raw body
 -> Trafilatura extraction
```

Do not use `trafilatura.fetch_url()` as the primary network fetch path in v1 because WebX needs explicit redirect, address, timeout, and size controls.

### Deliverable

`webx read URL` returns clean Markdown for normal HTML pages and rejects private/local network targets.

---

## Phase 6 — CLI completeness

Implement:

```text
webx init
webx doctor
webx up
webx stop
webx status
webx search ...
webx read ...
```

Optional diagnostic command:

```text
webx logs
```

Do not expose a giant command surface.

### Deliverable

CLI behavior and exit codes match `03_CLI_AND_CORE_SPEC.md`.

---

## Phase 7 — MCP adapter

Add the optional MCP integration only after the core and CLI are stable.

Use the official MCP Python SDK v2. Use stdio transport only for v1. Expose only:

- `web_search`
- `web_read`

Do not expose Docker lifecycle operations as agent tools. Lifecycle is internal to search.

### Deliverable

The MCP server can be tested with an in-memory MCP client or MCP Inspector, launches without starting SearXNG, and reuses the same search/read code as the CLI.

---

## Phase 8 — Tests, docs, polish

Run unit tests with no network dependency. Integration tests may use the local Docker SearXNG instance and public web, but mark them explicitly and do not require them for every fast unit-test run.

Before declaring completion, execute the end-to-end checklist in `07_TEST_AND_ACCEPTANCE.md` from a clean runtime directory.
