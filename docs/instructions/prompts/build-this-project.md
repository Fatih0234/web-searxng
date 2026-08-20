# Prompt to Start the Implementation in an Empty Folder

```text
Build the WebX project described by the instruction pack in this repository.

First read `AGENTS.md`, then all numbered specification files in order, then `SOURCES.md`. Treat those files as the product/build specification. Implement from an empty project folder rather than merely producing another plan.

Work in phases and keep the design small. The CLI and MCP adapter must share one Python core; SearXNG must be local-only and lazily started; the reader must enforce the URL/network safety requirements before content extraction. Do not add browser automation, LLM summarization, crawling, Valkey, reverse proxies, or other out-of-scope infrastructure unless a documented blocker requires it.

Run the unit tests throughout implementation and finish by executing the acceptance checklist in `07_TEST_AND_ACCEPTANCE.md`. If a current dependency/API differs from the researched specification, verify the current official documentation, make the smallest compatible adjustment, and document the deviation.
```
