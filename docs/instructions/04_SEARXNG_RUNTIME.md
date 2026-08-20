# 04 — SearXNG Runtime Specification

## Why SearXNG is private infrastructure

The user is not operating a public search instance. SearXNG exists only as a local backend for WebX. Therefore the v1 runtime should be deliberately smaller than public deployment templates.

## Required deployment properties

- one SearXNG container;
- Docker Compose;
- loopback port binding only: `127.0.0.1:8888:8080`;
- no Caddy/nginx/reverse proxy;
- no public TLS endpoint;
- `server.public_instance: false`;
- `server.limiter: false`;
- no Valkey/Redis in v1;
- `server.image_proxy: false`;
- autocomplete off by default;
- JSON result format enabled;
- default SearXNG engine configuration inherited rather than copied wholesale.

SearXNG documentation states that public-instance features are not needed for local usage and that the limiter requires Valkey. This is why the local v1 stack omits both limiter and Valkey.

## Packaged `settings.yml` template

Use a small override file, relying on SearXNG defaults:

```yaml
use_default_settings: true

general:
  debug: false
  instance_name: "webx"

search:
  safe_search: 0
  autocomplete: ""
  formats:
    - html
    - json

server:
  limiter: false
  public_instance: false
  image_proxy: false
```

Do not hardcode the secret in this file. Supply it using the documented `SEARXNG_SECRET` environment variable generated in `.env`.

JSON must be explicitly enabled because SearXNG's documented default search formats contain HTML only, and requesting a disabled format returns HTTP 403.

## Compose template

The coding agent should create a minimal Compose file roughly equivalent to:

```yaml
services:
  searxng:
    image: ${SEARXNG_IMAGE:-docker.io/searxng/searxng:latest}
    container_name: webx-searxng
    ports:
      - "127.0.0.1:8888:8080"
    env_file:
      - .env
    volumes:
      - ./settings.yml:/etc/searxng/settings.yml:ro
      - ./cache:/var/cache/searxng
    restart: "no"
```

Before finalizing this exact mount strategy, run it against the current official image. SearXNG's container image may attempt ownership changes on mounted paths (`FORCE_OWNERSHIP` behavior is documented). If a read-only single-file mount causes an issue, use a config directory mount or set the documented ownership environment setting appropriately. Preserve the design constraints; adjust only the mount mechanics.

Do not expose the container as `0.0.0.0:8888`.

## Image version strategy

During initial development, a current official image is acceptable. Before calling the implementation stable:

1. record the verified SearXNG image tag/digest in docs/tests;
2. make image selection configurable through `SEARXNG_IMAGE` or a `WEBX_` setting;
3. do not silently auto-pull on every search;
4. offer a documented manual update path.

At research time (2026-08-20), official SearXNG images use date/hash tags and an official `latest` tag. Do not assume that specific version forever.

## Runtime lifecycle

### Probe

Probe `http://127.0.0.1:8888/` with a short timeout. A successful HTTP response indicates the process is reachable without spending an external search query.

### Start

Use:

```text
docker compose -f <runtime>/compose.yml up -d
```

Then poll the root URL until ready or timeout. Do not use a fixed arbitrary sleep as the only readiness mechanism.

### Stop

Use:

```text
docker compose -f <runtime>/compose.yml stop
```

This should be the normal low-resource end-of-session action.

### Remove/reset

A separate maintenance path may use:

```text
docker compose ... down
```

Do not run `down` automatically at the end of every search session.

## SearXNG API

Use documented endpoint:

```text
GET /search
```

with at least:

```text
q=<query>
format=json
```

Supported useful documented request parameters include:

```text
categories
language
pageno
time_range = day | month | year
safesearch = 0 | 1 | 2
```

SearXNG also supports explicit engine selection. Keep this optional in WebX v1.

## Search engine tuning

Do not prematurely reduce SearXNG to a tiny custom engine list. Start with defaults and observe real results/error rates from the user's network.

Later tuning may use SearXNG's documented `use_default_settings.engines.remove` or `keep_only` features. Make such tuning a configuration choice rather than core WebX logic.

## Resource efficiency

When the container is stopped, SearXNG itself should consume no active CPU and essentially no process RAM. On macOS/Windows the container runtime/VM may still consume resources; WebX cannot eliminate that platform-level overhead. WebX's responsibility is to avoid keeping the SearXNG service running unnecessarily.
