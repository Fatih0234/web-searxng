# Verified SearXNG Image

- Verified at implementation: 2026-08-20
- Compose default: `${SEARXNG_IMAGE:-docker.io/searxng/searxng:latest}`
- Local image present at test time:
  - `docker.io/searxng/searxng:latest` → `ec536bcd1e83`
  - Digest: `sha256:ec536bcd1e83577aad4cc07f7ecb9a30858a9a905d2d57c8796abc83f872a036`
  - SearXNG version inside container: `2026.8.1-8892414dc` (`SearXNG 2026.8.1-8892414dc` in logs)
- `settings.yml` verified to contain `use_default_settings: true` and `formats: [html, json]` (JSON enabled, otherwise SearXNG returns 403 for format=json).
- `compose.yml` verified: `127.0.0.1:8888:8080`, no Valkey, single container `webx-searxng`, `restart: "no"`.
- Manual update path (see README):
  ```
  webx stop
  docker compose -f $(webx init --show-path)/compose.yml pull
  webx up
  webx search "test" --limit 1 --pretty
  webx stop
  ```
- Image is configurable via `SEARXNG_IMAGE` env var or `.env`; WebX never auto-pulls on search.

Note: At research time (2026-08-20) official images used date/hash tags plus `latest`. Do not assume this digest forever; update via manual pull and re-verify.
