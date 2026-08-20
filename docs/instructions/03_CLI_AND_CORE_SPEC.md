# 03 — CLI and Core Contract

## General CLI rules

- stdout is for requested data/results.
- stderr is for diagnostics, lifecycle notices, and errors.
- Commands must be scriptable and non-interactive by default.
- Never print secrets.
- Errors should include a short actionable message and stable non-zero exit code.
- The CLI must work from any current working directory after installation.

## Commands

### `webx init`

Materialize safe runtime assets and a secret. Does not start SearXNG.

Suggested output on stderr/stdout can be human-readable because this is an administrative command.

Options:

```text
--force-templates     replace generated compose/settings templates but preserve secret
--show-path           print resolved runtime path
```

Avoid a `--force` that silently rotates secrets.

### `webx doctor`

Check and report:

- Python/package version;
- resolved runtime directory;
- Docker executable availability;
- `docker compose version` success;
- runtime templates present/valid enough to use;
- loopback URL configuration;
- whether SearXNG is currently reachable;
- optional: Trafilatura version;
- optional: MCP dependency present.

`doctor` should not start SearXNG unless an explicit `--start` is later added. Default is inspection only.

### `webx up`

Explicitly ensure SearXNG is running and wait until reachable.

### `webx stop`

Execute Compose stop. This is the normal low-resource shutdown.

If already stopped, return success.

### `webx status`

Return concise status. A `--json` mode is useful.

Recommended JSON shape:

```json
{
  "initialized": true,
  "docker_available": true,
  "searxng_running": false,
  "url": "http://127.0.0.1:8888",
  "runtime_dir": "..."
}
```

### `webx search QUERY`

Options:

```text
--limit N                 default 8; reasonable hard cap such as 50
--category NAME           default general; pass through to SearXNG
--language CODE
--page N                  default 1
--time {day,month,year}
--safe-search {0,1,2}
--engine NAME             repeatable, optional
--pretty                   pretty-print JSON; default compact JSON is acceptable
```

Behavior:

1. lazy-start SearXNG;
2. query JSON API;
3. normalize/dedupe;
4. apply client-side limit;
5. output one JSON object.

Recommended envelope:

```json
{
  "query": "example",
  "results": [
    {
      "title": "Example",
      "url": "https://example.com",
      "snippet": "...",
      "engines": ["duckduckgo"],
      "score": 1.2,
      "category": "general",
      "published_date": null
    }
  ],
  "meta": {
    "result_count": 1,
    "page": 1,
    "category": "general",
    "time_range": null
  }
}
```

Do not generate a summary or answer. Search returns evidence candidates only.

### `webx read URL`

Default output: extracted Markdown/text on stdout.

Options:

```text
--max-chars N             default ~40000, with a hard safety cap
--json                    return structured JSON envelope
--links                   preserve links where Trafilatura supports it
--no-tables               omit tables
--precision               favor extraction precision
--recall                  favor extraction recall
```

Suggested `--json` shape:

```json
{
  "url": "requested URL",
  "final_url": "after redirects",
  "title": null,
  "content_type": "text/html",
  "content": "...",
  "truncated": false,
  "characters": 12345
}
```

Metadata can be expanded if Trafilatura supplies it reliably, but keep the schema backward-compatible.

## Exit codes

Use a small documented set. Suggested:

```text
0  success
2  invalid CLI usage / validation
3  local runtime or Docker unavailable
4  SearXNG search/start failure
5  unsafe/disallowed URL
6  page fetch/extraction failure
7  unsupported response content type
```

The exact numeric assignments may change before release, but once tests/docs establish them, treat them as part of the CLI contract.

## Core models

Use dataclasses or typed lightweight models; do not require a heavy validation framework.

Suggested models:

```text
SearchQuery
SearchResult
SearchResponse
ReadRequest
ReadResponse
RuntimeStatus
DoctorReport
```

Keep raw SearXNG response details internal. If a debugging raw mode is later needed, add it explicitly rather than leaking provider-specific fields into the stable schema.

## Logging

Default should be quiet. Optional `--verbose` can enable debug-level lifecycle information. Never write routine logs into stdout for data-producing commands.
