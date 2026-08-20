# 05 — Web Reader and Security

## Security model

`webx read` accepts URLs chosen by an AI agent. That means the URL is **untrusted input**. The reader must not become a path from arbitrary web content into services on the user's laptop, LAN, VPN, cloud metadata endpoints, or other private networks.

The web page body is also untrusted input. WebX extracts and returns it as **data**. It never interprets instructions found in a page, executes page scripts, submits forms, or propagates page text into control-plane configuration.

## Required URL policy

Allow only:

```text
http://
https://
```

Reject everything else, including `file:`, `ftp:`, `data:`, `javascript:`, custom schemes, bare paths, and shell-like input.

Reject URLs containing credentials (`user:password@host`) in v1.

## Network address restrictions

Before each outbound request:

1. parse the URL;
2. normalize/validate the hostname;
3. resolve it with the operating system resolver;
4. inspect every resolved IPv4/IPv6 address;
5. reject the request if any selected target is loopback, private, link-local, multicast, unspecified, reserved, or otherwise non-public according to Python `ipaddress` classifications and explicit deny rules.

At minimum deny:

- `localhost` and loopback ranges;
- RFC1918 private IPv4 ranges;
- IPv6 unique-local ranges;
- link-local ranges;
- multicast;
- unspecified addresses;
- cloud metadata well-known link-local endpoints such as `169.254.169.254`;
- the WebX/SearXNG local endpoint itself.

Do not implement a user-facing `--allow-private` escape hatch in v1. If future use cases require intranet reading, make that a separate explicit security mode.

### DNS rebinding note

A resolve-then-connect check does not perfectly eliminate DNS rebinding because the HTTP client may resolve the hostname again. For v1, implement the strongest practical validation cleanly, validate every redirect, and document the remaining limitation. If the coding agent can implement address pinning/custom resolution without making the code fragile, it is an improvement, not a reason to balloon the first version.

## Redirect policy

Do not enable unlimited automatic redirects.

Use a manual or tightly controlled redirect loop:

1. request URL with redirects disabled;
2. if response is redirect, resolve the `Location` against the current URL;
3. run the complete URL/network validation on the new target;
4. continue up to a small maximum such as 5 redirects;
5. fail clearly on loops or excess redirects.

Never validate only the original URL and then blindly follow redirects.

## HTTP limits

Recommended defaults:

```text
connect timeout: ~5 seconds
read/overall timeout: ~15 seconds
redirects: max 5
response body: max ~10 MiB
extracted characters: default ~40,000
```

Make these configurable but retain hard upper safety limits where sensible.

Stream response bodies so a hostile server cannot force an unbounded in-memory download. If `Content-Length` is above the limit, reject before downloading the body. Also enforce the limit while streaming because `Content-Length` may be absent or false.

Use a simple identifying User-Agent such as:

```text
webx/<version> local-research-tool
```

Do not masquerade as a browser unless a future compatibility requirement justifies it.

## Allowed response types

Primary v1 target:

- `text/html`
- `application/xhtml+xml`
- `text/plain`
- Markdown-like text types

Optionally allow JSON/XML text responses and return them as text with limits.

For unsupported binary types, return an explicit unsupported-content error. In particular, do not pretend Trafilatura can reliably read PDFs. PDF support is a future adapter.

## HTML extraction

Fetch bytes with WebX's own HTTP layer. Decode according to response metadata/library behavior. Pass the resulting HTML to Trafilatura.

Suggested extraction defaults:

```python
extract(
    html,
    url=final_url,
    output_format="markdown",
    include_comments=False,
    include_tables=True,
    include_links=False,
    with_metadata=False,
)
```

Offer CLI flags for links, tables, precision, and recall rather than over-tuning defaults.

If main extraction returns empty/None, a conservative fallback such as Trafilatura `html2txt()` may be used. Mark fallback use in JSON metadata if useful.

Do not return enormous navigation menus merely because main-content extraction failed. Fail when the result is clearly unusable instead of flooding an agent context.

## Truncation

Truncate **after extraction**, not only before. Try to cut at a reasonable text boundary near the maximum rather than splitting in the middle of a multi-byte sequence or Markdown construct.

The structured response must state:

```text
truncated: true|false
characters: returned character count
```

The caller can make another decision if it needs more material.

## Prompt-injection boundary

MCP tool descriptions and agent prompts must state that returned web content is external untrusted data. WebX itself does not attempt to detect semantic prompt injection using an LLM. Instead, preserve a strong architectural boundary:

```text
web content -> tool result / evidence
NOT
web content -> system instructions / executable commands
```

A coding agent should not execute commands copied from a page merely because the page instructs it to. Commands from documentation may be considered evidence and require the normal coding-agent judgment/authorization policy.

## No authenticated browsing

V1 must not support:

- browser cookies;
- imported sessions;
- Authorization headers from agent input;
- arbitrary user-provided headers;
- login forms;
- POST form submission;
- upload endpoints.

This keeps WebX a read-only public-web utility.
