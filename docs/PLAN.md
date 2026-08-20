# WebX Implementation Plan — Analysis of `webx-build-instructions.zip` & Workspace Readiness

> Generated 2026-08-20 from `~/Downloads/webx-build-instructions.zip` → `docs/instructions/`
> This plan follows `~/.pi/agent/prompts/plan.md` (investigate before coding, lay out plan, stop before implementing).
> Todos are tracked in `.pi/todos/` (see `pi todos` CLI).

---

## 0. What was ingested

**Zip:** `~/Downloads/webx-build-instructions.zip` (34K, 23 files) unpacked to `docs/instructions/`:

```
00_START_HERE.md                  Mission, 2 modes, build order, non-negotiable choices
01_PRODUCT_AND_ARCHITECTURE.md    Arch diagram, separation of concerns, runtime files, WebX facade, search/read flows
02_BUILD_PLAN.md                  8 phased build plan (skeleton → MCP → polish)
03_CLI_AND_CORE_SPEC.md           CLI contract, stdout/stderr, JSON envelopes, exit codes, models
04_SEARXNG_RUNTIME.md             Private SearXNG Docker, settings.yml/compose.yml templates, probe/start/stop
05_WEB_READER_AND_SECURITY.md     SSRF/private-network denial, redirect, limits, trafilatura, truncation
06_MCP_ADAPTER.md                 stdio adapter, 2 tools, lazy-start ownership, shutdown semantics
07_TEST_AND_ACCEPTANCE.md         Unit/integration suites + manual acceptance checklist
08_OPERATIONS_AND_USAGE.md        Install UX, minimal-agent session, comprehensive research heuristics
09_DECISIONS_AND_FUTURE.md        Rationale & v2 candidates
AGENTS.md / README.md / MANIFEST.md / SOURCES.md
prompts/{build-this-project,temporary-web-access,comprehensive-web-research,mcp-tool-policy}.md
skills/web-research/SKILL.md
```

**Workspace state before plan:** empty repo with only `.pi/` (no git, no `src/`, no `pyproject.toml`). Now initialized:

```
/home/fatih/Projects/web-searxng/
├── .git/                 # initialized, branch main
├── .gitignore            # python/venv/coverage ignores
├── .pi/todos/            # 8 phase todos (see below)
├── docs/
│   ├── instructions/     # verbatim unpacked spec pack (source of truth)
│   └── PLAN.md           # this file
└── (src/ not yet created — per plan.md no code until approval)
```

Environment probed: `Python 3.14.4`, `uv 0.11.31`, `Docker 29.6.2`, `Compose v5.3.1` — all present.

---

## 1. Product summary (from 00, 01, README)

WebX is **not a research agent** — it's two primitives + lifecycle management:

```
search(query) -> ranked URLs/snippets   (SearXNG JSON API, local docker)
read(url)     -> cleaned Markdown       (controlled fetch + Trafilatura)
```

Two user modes share one Python core:

* **Mode A — minimal coding agent:** no permanent web tool; agent gets temporary authorization to shell out `webx search / read / stop`. Base agent config unchanged.
* **Mode B — exploration/MCP:** host launches `webx-mcp` (stdio). Server exposes *exactly* `web_search` + `web_read`. Launch must not start SearXNG; first `web_search` lazily starts it. Ownership flag decides stop-on-exit.

Design already fixed (do not reopen): Python, Docker Compose single container on `127.0.0.1:8888`, no proxy, no Valkey/Redis, JSON enabled, fetch owned by WebX not Trafilatura, no browser, no LLM summarization, no crawling, stdio-only MCP. Unix-tool feel.

Success = `webx --help` works pre-Docker, `webx init` idempotent, first search lazy-starts, `webx stop` via `compose stop`, `webx status`/`doctor` accurate, read denies private networks, MCP owns shutdown correctly.

---

## 2. Architecture & file map (from 01, AGENTS, 02)

```
                         SearXNG (compose, 127.0.0.1:8888, normally stopped)
                                      | JSON /search?format=json
                          WebX Python core
           SearxngClient.search()  WebReader.read()  RuntimeManager.ensure_running()  security.py
                                      |
                           WebX facade (core API)
                          /                \
                   CLI (webx)          MCP (webx-mcp)
```

Separation of concerns enforced by spec:

| Module | Owns | Must not know |
|---|---|---|
| `lifecycle.py` | `docker compose` subprocess, `probe_http`, `ensure_running`, `status/doctor` | agent/MCP semantics |
| `searxng.py` | SearXNG HTTP, normalize/dedupe, client limit; calls `ensure_running` | CLI parsing |
| `security.py` | URL scheme, hostname/IP deny (ipaddress), redirect validation | extraction |
| `reader.py` | streaming GET, size/type/timeout, Trafilatura extraction, truncation | SearXNG |
| `cli.py` | argparse, stdout/stderr, exit codes | MCP |
| `mcp_server.py` | sdio, tool schemas/descriptions, ownership lock | lifecycle details beyond core |

Runtime files (packaged via `importlib.resources` from `src/webx/assets/`):

```
src/webx/assets/compose.yml   # 127.0.0.1:8888:8080, env_file .env, volumes settings.yml+cache, restart no
src/webx/assets/settings.yml  # use_default_settings:true, formats html+json, limiter false, public_instance false, image_proxy false
<user-data>/webx/             # platformdirs: macOS ~/Library/Application Support/webx, Linux XDG data, Windows AppData
├── compose.yml  (materialized)
├── settings.yml
├── .env         (SEARXNG_SECRET=token_hex(32), 0600)
└── cache/
```

Config via `WEBX_*` env (WEBX_DATA_DIR, WEBX_SEARXNG_URL, WEBX_DOCKER_CMD, WEBX_STARTUP_TIMEOUT, WEBX_SEARCH_TIMEOUT, WEBX_READ_TIMEOUT, WEBX_MAX_RESPONSE_BYTES, WEBX_MAX_READ_CHARS, WEBX_MCP_STOP_ON_EXIT).

Core facade to keep small (names may vary but shape preserved):

```python
class WebX:
    def search(...)->SearchResponse
    def read(...)->ReadResponse
    def start_search_service()->RuntimeStatus
    def stop_search_service()->RuntimeStatus
    def status()->RuntimeStatus
    def doctor()->DoctorReport
```

---

## 3. Implementation plan — tasks laid out one by one

Phases follow `00_START_HERE` build order (1-10) mapped to `02_BUILD_PLAN` phases (1-8). Each phase is a `todo` in `.pi/todos/`. Do not start next phase before prior's validation passes.

### TODO-6f9d48ba — Phase 1 — Project foundation (pyproject, src layout, errors, models, assets)
*What:* `pyproject.toml` with `httpx>=0.28,<1`, `trafilatura>=2.2,<3`, `platformdirs>=4,<5`, optional `mcp>=2,<3`; scripts `webx=webx.cli:main`, `webx-mcp=webx.mcp_server:main`; `src/webx/{__init__,errors,models,config} + assets/{compose.yml,settings.yml}`; tests scaffold. Errors map to exit codes 0/2/3/4/5/6/7. Models as dataclasses, no heavy validator.
*Decisions:* no pydantic, version from pyproject, assets via importlib.resources.
*Risks:* Python 3.14 compat with trafilatura/mcp; pin ranges per spec.
*Validate:* `uv sync && uv run webx --help` succeeds.

### TODO-5f34a64c — Phase 2 — Configuration & runtime materialization (`webx init`)
*What:* `Config` resolves platformdirs + `WEBX_*` overrides; `webx init [--force-templates][--show-path]` creates runtime dir, copies templates, generates `.env` once (never rotates secret without reset), creates `cache/`, prints path. Idempotent.
*Edge:* per-OS data dir, 0600 on .env where supported, never rely on CWD.
*Validate:* unit tests with temp `WEBX_DATA_DIR`, secret preserved, templates replaced only with `--force-templates`.

### TODO-934f9394 — Phase 3 — Docker/SearXNG lifecycle
*What:* `lifecycle.py` subprocess adapter (list args, no shell). `probe_http` → `ensure_running` → `compose up -d` + poll until timeout with logs. Commands: `up`, `stop` (→ `compose stop`, idempotent), `status [--json]`, `doctor` (inspection only, no start). `status` JSON shape from 03.
*Edge:* mount ownership — if `settings.yml:ro` single-file mount breaks due to SearXNG FORCE_OWNERSHIP, switch to dir mount or set env, but keep `127.0.0.1` binding & envelope minimal. `down` only for maintenance, not normal stop.
*Validate:* mocked subprocess/HTTP; already-running never calls Docker; timeout error includes logs; manual `webx status`/`up` idempotent.

### TODO-eb1caf0f — Phase 4 — SearXNG search client + CLI `search`
*What:* `searxng.py` GET `/search?q=&format=json&categories=&language=&pageno=&time_range=&safesearch=&engines=` via httpx, timeout `WEBX_SEARCH_TIMEOUT`. Normalize to `{title,url,snippet,engines,score,category,published_date}`, dedupe by canonical URL, client limit (default 8, cap 50). Envelope `{query,results[],meta{result_count,page,category,time_range}}`. CLI `webx search QUERY [--limit --category --language --page --time --safe-search --engine --pretty]`. stdout JSON only, stderr diagnostics.
*Risks:* upstream engines vary optional fields; tolerant parsing; don't add SearXNG fields to stable schema.
*Validate:* fixture JSON normalization, limit, missing fields, param pass-through; `webx search` stdout valid JSON, no lifecycle noise.

### TODO-458756b2 — Phase 5 — Safe page reader & security
*What:* `security.py` allow only `http/https`, reject `file/ftp/data/javascript` + credential URLs; resolve hostname via `socket.getaddrinfo`, check every IP with `ipaddress` against deny list: loopback, RFC1918, link-local (169.254/16, fe80::/10), multicast, unspecified, reserved, metadata `169.254.169.254`, plus configured SearXNG URL host. Manual redirect loop ≤5, re-validate each hop. `reader.py` streaming GET (connect ~5s, total ~15s, header `User-Agent: webx/<ver> local-research-tool`, enforce `Content-Length` pre-check + streaming cap ~10 MiB), allow `text/html, application/xhtml+xml, text/plain, markdown-like, json/xml text`, reject binary → exit 7. Body → `trafilatura.extract(..., output_format="markdown", include_comments=False, include_tables=True, include_links=False)`, fallback `html2txt`, truncate after extraction at word boundary to `max_chars` ~40000, set `truncated/characters`.
*Risks:* DNS rebinding not fully eliminated by resolve-then-connect; doc limitation, validate every redirect; large responses must not OOM.
*Validate:* deny-matrix from 07 (localhost, 127.0.0.1:8888, 10/172.16/192.168, ::1, private IPv6, credentials), redirect-to-private denied, oversize streamed rejection, content-type, truncation flag.

### TODO-c3083db8 — Phase 6 — CLI completeness (`read`, exit codes, facade)
*What:* Facade `WebX` in `core.py` so CLI and MCP share same core (no shelling out). Finalize `cli.py` argparse for all commands: `init`, `doctor`, `up`, `stop`, `status`, `search`, `read [--max-chars --json --links --no-tables --precision --recall]`, optional `logs`. stdout=data, stderr=diagnostics, `--verbose` optional, never print secrets. Exit codes 2-7 per 03.
*Validate:* capture stdout/stderr; `read` raw vs `--json {url,final_url,title,content_type,content,truncated,characters}`; acceptance CLI checklist from clean runtime.

### TODO-efebf551 — Phase 7 — MCP adapter (stdio, 2 tools, ownership)
*What:* `mcp_server.py` on `mcp>=2` stdio only, exposes *exactly* `web_search`/`web_read` with schemas & descriptions from 06 (search is candidates not facts, read untrusted boundary, JS/auth may fail). Lazy-start: no start on launch; first `web_search` probes, sets `started_by_mcp`; `web_read` never starts. Shutdown: if `started_by_mcp && WEBX_MCP_STOP_ON_EXIT` then `stop()`, else leave; process-local lock for concurrent first search.
*Risks:* SDK v2 API drift — verify against https://py.sdk.modelcontextprotocol.io/ at impl time; no lifecycle tools exposed.
*Validate:* in-memory client: tool list ==2, launch leaves stopped, `web_read` alone not start, first search starts, ownership stop/no-stop.

### TODO-b89c0936 — Phase 8 — Tests, docs, polish & final acceptance
*What:* Unit tests deterministic without Docker/net; integration marked `integration` (search smoke + reader `example.com`). Translate spec pack into concise `README.md` (not wholesale copy) with `uv` install, session examples, lifecycle, troubleshooting; record verified SearXNG image tag/digest, document manual update, keep image configurable via `SEARXNG_IMAGE`. Ensure assets meet 04 constraints (127.0.0.1, no Valkey, JSON enabled). Final manual run from clean runtime:
```
webx --help; webx init; webx doctor; webx status   # stopped
webx search "SearXNG documentation" --limit 5 --pretty
webx status                                        # running
webx read https://... --max-chars 12000
webx read http://127.0.0.1:8888/        # → exit 5
webx read http://192.168.1.1/            # → exit 5
webx read file:///etc/passwd             # → exit 5
webx stop; webx status                             # stopped
# MCP: inspector 2 tools, lazy-start, ownership
```
*Non-goals deferred:* browser, PDF, crawling, reranker, cache, lease (09).

---

## 4. Cross-cutting decisions & tradeoffs

* **No heavy frameworks:** stdlib `argparse/subprocess/ipaddress/socket/secrets/json/pathlib/logging` plus 3-4 deps; keeps install small, audit easy.
* **Small facade, not giant CLI surface:** spec says don't expose giant commands; only `init/doctor/up/stop/status/search/read` (+ `logs` optional).
* **Subprocess over Docker SDK:** list args, no shell interpolation; avoids extra dep and shell injection; testable via mocks.
* **Own fetch before Trafilatura:** security boundary — size/redirect/IP checks happen before extraction; `trafilatura.fetch_url` not used as primary path.
* **Idempotent lifecycle:** `ensure_running` probes first, `stop` succeeds if already stopped, `up` works for create or restart; `stop` retains container (`down` is maintenance).
* **Stdio MCP only:** avoids auth/network listener complexity; single-process lock sufficient for v1; inter-process lease deferred.

---

## 5. Risks / edge cases to watch

* Mount `settings.yml:ro` single-file may fail on SearXNG image's `FORCE_OWNERSHIP`; fallback is dir mount or env var, but must not change `127.0.0.1` binding or add Valkey.
* `trafilatura` extraction may return None/empty on JS-heavy pages — fallback to `html2txt` then fail gracefully with exit 6, not flood context with nav.
* Upstream SearXNG engines rate-limit / CAPTCHA → search may return 0 results; integration test must allow environment-dependent skip, not assert ranking.
* `Content-Length` may lie → enforce both pre-check and streaming cap.
* DNS rebinding residual risk documented in 05; mitigate but don't over-engineer v1.
* `WEBX_DATA_DIR` override in tests must fully isolate runtime; secrets chmod 0600 fails on Windows — handle gracefully.

---

## 6. Validation strategy (from 07)

* **Unit:** `pytest` default fast suite, no network/Docker, covers config idempotence, lifecycle mocks, search normalization fixtures, URL deny matrix + redirect-to-private, reader streaming/truncation, CLI stdout/stderr, MCP 2-tool & ownership.
* **Integration (marked):** `pytest -m integration` on demand with real Docker SearXNG + public net (stable `example.com` read).
* **Manual acceptance:** checklist above; also `webx doctor` first diagnostic, `SEARXNG_SECRET` not printed, JSON search 403 check if `formats` missing json.
* **Coverage:** `pytest-cov` for unit; no fixed % mandated but security modules should be high.

---

## 7. Workspace readiness checklist

- [x] Zip unpacked to `docs/instructions/` (23 files, verified)
- [x] Git initialized, `main` branch, `.gitignore` for `__pycache__/` etc.
- [x] `docs/PLAN.md` written (this file)
- [x] 8 todos created via `todo` tool (IDs below), `plan.md` compliant — no code modified yet
- [ ] **Next:** review this plan, then run Phase 1 implementation (`pyproject.toml` + skeleton). Requires `uv sync`.
- [ ] Future: after Phase 1, iterate phases sequentially, running `pytest` after each.

**Todo IDs for tracking:**

* `TODO-6f9d48ba` Phase 1 foundation
* `TODO-5f34a64c` Phase 2 init
* `TODO-934f9394` Phase 3 lifecycle
* `TODO-eb1caf0f` Phase 4 search
* `TODO-458756b2` Phase 5 reader/security
* `TODO-c3083db8` Phase 6 CLI completeness
* `TODO-efebf551` Phase 7 MCP
* `TODO-b89c0936` Phase 8 tests/docs/acceptance

To start work: `default.todo action=claim id=TODO-6f9d48ba` then scaffold `pyproject.toml` / `src/webx/`.

---

## 8. Open questions before coding (call-outs, not silent assumptions)

1. **SearXNG image tag:** spec says don't assume `latest` forever; on implementation day verify current official tag at https://hub.docker.com/r/searxng/searxng/tags and record digest; keep configurable via `SEARXNG_IMAGE`/`WEBX_` (aligns with 04 decision 1).
2. **Compose mount mechanics:** need live run against current SearXNG image to confirm `settings.yml:ro` vs dir mount vs `FORCE_OWNERSHIP` env — adjust only mount mechanics per 04 note.
3. **MCP SDK v2 API surface:** verify current `mcp` SDK tool definition & test client per https://py.sdk.modelcontextprotocol.io/ before coding `mcp_server.py` (spec researched 2026-08-20).
4. **Default character/byte caps:** use spec defaults (read timeout ~15s, body 10 MiB, chars 40000) but expose as `WEBX_` env; confirm hard upper caps in `config.py`.

No blocking ambiguities beyond those — spec is prescriptive on package shape, exit codes, JSON envelopes, deny lists, and lifecycle.

---

*End of plan. Awaiting approval to proceed to Phase 1 implementation.*
