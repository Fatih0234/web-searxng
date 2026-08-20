# 07 — Test and Acceptance Plan

## Testing philosophy

Most tests must be deterministic and run without Docker or the public internet. Separate pure/unit tests from live integration tests.

## Unit tests

### Configuration

Test:

- platform data directory override;
- environment-variable parsing;
- default loopback base URL;
- invalid timeout/size values;
- runtime asset materialization idempotence;
- existing secret is never silently replaced.

### Lifecycle

Mock subprocess and HTTP probes. Test:

- already-running path never calls Docker;
- stopped path calls `docker compose ... up -d`;
- readiness polling stops on success;
- readiness timeout produces useful error;
- `stop` is idempotent;
- command arguments are passed as arrays, not interpolated shell strings.

### Search normalization

Use fixture JSON. Test:

- required fields normalized;
- missing optional fields tolerated;
- duplicate URLs deduplicated;
- result limit applied client-side;
- malformed backend response produces typed error;
- query/category/time/page parameters are sent correctly.

### URL security

This is a high-priority test suite. Include cases for:

```text
http://example.com              allowed if resolves publicly in mocked resolver
https://example.com             allowed
file:///etc/passwd              denied
ftp://example.com               denied
http://localhost                denied
http://127.0.0.1                denied
http://127.0.0.1:8888           denied
http://10.0.0.1                 denied
http://172.16.0.1               denied
http://192.168.1.1              denied
http://169.254.169.254          denied
http://[::1]                    denied
private/unique-local IPv6       denied
credential-bearing URL          denied
```

Mock DNS so tests do not depend on external resolution.

Test redirect validation specifically: public URL redirecting to private URL must be denied before the second request.

### Reader

With mocked HTTP responses, test:

- HTML extraction;
- plain-text passthrough;
- missing/invalid content type policy;
- oversized `Content-Length` rejection;
- streamed body exceeding max bytes rejection;
- redirect count cap;
- extraction fallback;
- max-character truncation and flag;
- comments disabled by default.

### CLI

Capture stdout/stderr. Test:

- search stdout is valid JSON;
- lifecycle notices never contaminate search stdout;
- read raw mode returns content;
- read `--json` returns schema;
- exit codes map correctly.

### MCP

With mocked/shared core:

- exactly two tools exposed;
- no startup during MCP initialization;
- `web_search` invokes core search;
- `web_read` invokes core read;
- cleanup only stops service when MCP started it.

## Integration tests

Mark with `integration` and skip unless explicitly enabled.

### Local SearXNG smoke test

From a fresh temporary WebX runtime:

1. `webx init`;
2. confirm `webx status` says stopped;
3. run a search for a stable query;
4. validate JSON has at least one well-formed result or provide a clear environment-dependent skip if upstream engines are blocked;
5. confirm SearXNG is now running;
6. run second search without container recreation;
7. run `webx stop`;
8. confirm stopped.

### Live reader smoke test

Read a stable public HTML test page such as `https://example.com/` and verify clean text extraction.

Do not make integration tests depend on a specific search engine result ranking.

## Manual acceptance checklist

Run from the final package environment:

```bash
webx --help
webx init
webx doctor
webx status
```

At this point SearXNG must still be stopped.

Then:

```bash
webx search "SearXNG documentation" --limit 5 --pretty
webx status
```

SearXNG should now be running.

Pick a public HTML result and run:

```bash
webx read "https://..." --max-chars 12000
```

Then verify denial:

```bash
webx read "http://127.0.0.1:8888/"
webx read "http://192.168.1.1/"
webx read "file:///etc/passwd"
```

All must fail safely with the unsafe-URL exit class.

Finish:

```bash
webx stop
webx status
```

SearXNG must be stopped.

## MCP acceptance

Start `webx-mcp` through the current MCP Inspector/host configuration.

Verify:

- tool list contains only `web_search` and `web_read`;
- SearXNG is not running before a search;
- `web_read("https://example.com")` works while SearXNG remains stopped;
- first `web_search` starts SearXNG;
- multiple searches reuse it;
- terminating MCP stops SearXNG if MCP started it;
- if SearXNG was manually started before the MCP search, terminating MCP leaves it running.

## Definition of acceptable v1 limitations

The following are acceptable and should be documented rather than "fixed" with large dependencies:

- occasional upstream SearXNG engine rate limits/CAPTCHAs;
- JS-heavy pages may yield little content;
- authenticated pages unsupported;
- PDFs unsupported by `web_read`;
- no screenshots/browser interactions;
- no semantic reranker or LLM summarizer;
- no persistent research database.
