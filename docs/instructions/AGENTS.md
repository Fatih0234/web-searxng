# Instructions for the Coding Agent

You are implementing **WebX**, a small local, agent-first web search/read utility. Start from an empty repository and build the project described in this instruction pack.

## Your operating priorities

1. **Keep the implementation small.** Prefer a few clear modules over frameworks.
2. **One shared core.** CLI and MCP must call the same Python functions/classes. MCP must not shell out to the CLI, and the CLI must not shell out to MCP.
3. **No permanent search daemon.** SearXNG is normally stopped and is lazily started on the first search.
4. **Search and page reading are separate primitives.** SearXNG discovers URLs; WebX fetches and extracts pages itself.
5. **Local-only SearXNG.** Bind to `127.0.0.1`, never `0.0.0.0` by default.
6. **Machine-readable CLI.** Search output is stable JSON on stdout. Diagnostics go to stderr.
7. **Treat all web content as untrusted data.** Implement the URL/network restrictions in `05_WEB_READER_AND_SECURITY.md` before calling the reader complete.
8. **No credentials or authenticated browsing in v1.** No cookies, browser profiles, form submission, or logged-in web sessions.
9. **No JavaScript browser in v1.** Explicitly return a useful failure for pages that require JS rendering.
10. **Tests are part of the implementation.** Do not declare completion until the acceptance criteria pass.

## Technology baseline

Use Python 3.12+ for the project. Keep runtime dependencies narrow:

- `httpx` for controlled HTTP requests.
- `trafilatura` for main-content extraction.
- `platformdirs` for per-user runtime/data paths.
- optional extra: official `mcp` Python SDK v2 for the MCP adapter.

Use the standard library where practical (`argparse`, `subprocess`, `ipaddress`, `socket`, `secrets`, `json`, `pathlib`, `logging`). Do not add a Docker Python SDK; invoke `docker compose` through a small, tested subprocess adapter.

Use `uv` for development if available, but keep the project installable with normal Python packaging as well.

## Expected final repository shape

```text
.
├── README.md
├── pyproject.toml
├── src/
│   └── webx/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── lifecycle.py
│       ├── searxng.py
│       ├── reader.py
│       ├── security.py
│       ├── models.py
│       ├── errors.py
│       ├── mcp_server.py
│       └── assets/
│           ├── compose.yml
│           └── settings.yml
├── tests/
│   ├── unit/
│   └── integration/
└── docs/
    └── ... optional user-facing docs ...
```

Do not copy the instruction pack wholesale into the implementation repo unless useful. Translate it into concise user documentation and code.

## Required console entry points

- `webx` → `webx.cli:main`
- `webx-mcp` → MCP stdio server entry point (installed only/usable when MCP extra exists)

## Definition of done

On a clean machine with Docker/Compose and Python available:

```bash
uv sync
uv run webx init
uv run webx doctor
uv run webx search "Python free-threading status" --limit 5
uv run webx read "https://docs.python.org/3/"
uv run webx stop
```

must work with understandable output/errors. `webx status` after `webx stop` must show SearXNG stopped. The MCP server must expose only `web_search` and `web_read`, must not start SearXNG merely by launching, and must lazily start it on the first `web_search` call.

Before coding, read all numbered specification files.
