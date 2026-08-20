# 08 — Operations and Usage

## Installation UX target

After the project is implemented, a user should be able to do roughly:

```bash
uv tool install .
webx init
webx doctor
```

or install it through standard Python packaging.

`webx init` should tell the user where runtime assets live and that SearXNG is currently stopped.

## Normal minimal-agent session

User gives the coding agent a temporary authorization prompt (see `prompts/temporary-web-access.md`). The agent may run:

```bash
webx search "current upstream documentation for X" --limit 8
webx read "https://primary-source.example/..."
webx read "https://another-source.example/..."
```

If more evidence is required:

```bash
webx search "narrower follow-up query" --category it
```

At task end:

```bash
webx stop
```

The user's ordinary agent system prompt remains free of web-search instructions.

## Comprehensive research behavior

"Comprehensive" is an agent behavior, not a special WebX endpoint. The agent should:

1. search broadly to discover terminology/actors;
2. inspect result provenance;
3. formulate several narrower queries;
4. prioritize primary/official sources;
5. read important pages rather than relying on snippets;
6. search specifically for contradictions or missing claims;
7. stop when additional searches are unlikely to change the conclusion;
8. report source URLs in its answer.

Do not implement `webx research`, `webx answer`, or `webx summarize` in v1.

## Coding research heuristics

For technical work, the agent should usually prefer evidence in roughly this order when available:

1. official project documentation;
2. upstream repository/release notes/issues or pull requests relevant to the claim;
3. specifications/standards;
4. official vendor/project announcements;
5. high-quality technical writing;
6. community discussions as supporting experience, not authoritative API truth.

Use `--category it` when it improves SearXNG results, but do not assume category behavior is identical across every SearXNG release/engine set.

## Service lifecycle

### Start explicitly

```bash
webx up
```

### Check

```bash
webx status
```

### Stop without deleting container

```bash
webx stop
```

This is the normal action after a research session.

### Maintenance

The implementation may document a lower-level reset/remove procedure using Compose `down`. Do not make destruction of runtime state the normal workflow.

## Updates

SearXNG changes rapidly. Provide a documented manual update procedure rather than automatic background updates.

Recommended maintenance concept:

```text
webx stop
update configured SearXNG image tag / pull intentionally
webx up
run smoke test
webx stop
```

Never auto-update dependencies or container images merely because the agent searched the web.

## Troubleshooting

`webx doctor` is the first command.

Useful failure classes and likely causes:

### Docker/Compose unavailable

Tell the user Docker or compatible Compose is required for SearXNG search. `webx read` may still work because it does not need SearXNG.

### SearXNG starts but searches fail

Inspect Compose logs and SearXNG engine errors. Upstream engines may rate-limit or CAPTCHA the user's IP. Do not hide this by silently querying a paid fallback in v1.

### JSON search returns 403

Verify `json` remains enabled under `search.formats` in the generated SearXNG settings.

### Reader returns too little text

Try `--recall`, inspect whether the site is JS-rendered, or use a different source. Do not automatically launch a headless browser in v1.

### Reader rejects a URL

Show which safety class caused denial without leaking sensitive resolver details. Private/local targets are intentionally unsupported.
