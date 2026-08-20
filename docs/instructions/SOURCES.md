# Sources and Version Notes

Research date: **2026-08-20**.

These are the authoritative/current references used to create this build specification. The implementation agent should re-check them if current package APIs differ during implementation.

## SearXNG

### Search API

Official SearXNG Search API documentation:

- https://docs.searxng.org/dev/search_api.html

Key points used by this spec:

- `/` and `/search` support GET/POST search requests.
- JSON output uses `format=json`.
- Output formats must be enabled in `settings.yml`; otherwise a request can return 403.
- useful parameters include `categories`, `language`, `pageno`, `time_range`, and `safesearch`.

### Search settings

- https://docs.searxng.org/admin/settings/settings_search.html

Key point: documented default `search.formats` contains HTML, so WebX explicitly enables JSON.

### General settings / `use_default_settings`

- https://docs.searxng.org/admin/settings/settings.html

Key point: a small local settings override can inherit SearXNG defaults using `use_default_settings: true`; engine lists can later use `remove` or `keep_only` without copying the entire default configuration.

### Server settings

- https://docs.searxng.org/admin/settings/settings_server.html

Key points:

- `SEARXNG_SECRET` overrides `server.secret_key`.
- limiter requires a Valkey database.
- `public_instance` features are not needed for local usage.
- image proxy consumes memory and is unnecessary for WebX's local JSON API use.

### Container installation

- https://docs.searxng.org/admin/installation-docker

Key points:

- Compose is the recommended container deployment method.
- official images are published to DockerHub/GHCR.
- `/etc/searxng` and `/var/cache/searxng` are documented container volumes.
- `SEARXNG_*` environment variables configure the container.
- `FORCE_OWNERSHIP` behavior exists for mounted data/config.

### Official image tags

- https://hub.docker.com/r/searxng/searxng/tags

At research time, official date/hash tags and `latest` were available. The implementation must not assume a 2026-specific tag forever.

## Trafilatura

### Python usage

- https://trafilatura.readthedocs.io/en/latest/usage-python.html

Key points:

- `extract()` is the main extraction function.
- Markdown output is supported.
- extraction can include/exclude comments, tables, links, metadata, and formatting.

### Quickstart

- https://trafilatura.readthedocs.io/en/latest/quickstart.html

Key points:

- URLs can be fetched/extracted by Trafilatura itself, but WebX intentionally separates network fetching from extraction for security control.
- Markdown output and metadata extraction are supported.

### Core functions

- https://trafilatura.readthedocs.io/en/latest/corefunctions.html

Key point: current function signatures support `output_format="markdown"`, `include_comments`, `include_tables`, `include_links`, precision/recall behavior, and related options.

## Model Context Protocol Python SDK

### Official Python SDK

- https://py.sdk.modelcontextprotocol.io/
- https://py.sdk.modelcontextprotocol.io/get-started/

At research time, **v2 is the current stable Python SDK line**. It supports tools and stdio transport and documents development/testing flows. WebX should use the current stable v2 API rather than copying old v1 examples.

## Design notes that are project decisions, not upstream requirements

The following are WebX choices:

- SearXNG bound only to loopback.
- local private instance omits Valkey and disables limiter/public-instance features.
- first search lazy-starts SearXNG.
- normal shutdown uses Compose `stop` rather than `down`.
- WebX owns HTTP fetching so it can enforce URL/network/redirect/size controls before Trafilatura extraction.
- CLI search returns normalized JSON without summarization.
- MCP exposes only `web_search` and `web_read`.
