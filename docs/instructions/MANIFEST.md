# Instruction Pack Manifest

- `README.md` — overview and reading order.
- `AGENTS.md` — top-level instructions for the coding agent.
- `00_START_HERE.md` — mission, modes, non-negotiable design choices.
- `01_PRODUCT_AND_ARCHITECTURE.md` — component architecture and lifecycle model.
- `02_BUILD_PLAN.md` — phased implementation plan from an empty repository.
- `03_CLI_AND_CORE_SPEC.md` — CLI commands, output schemas, exit behavior, core models.
- `04_SEARXNG_RUNTIME.md` — local Docker/SearXNG configuration and lifecycle.
- `05_WEB_READER_AND_SECURITY.md` — fetching, SSRF/private-network defenses, extraction limits.
- `06_MCP_ADAPTER.md` — optional stdio MCP adapter and lazy-start ownership semantics.
- `07_TEST_AND_ACCEPTANCE.md` — unit/integration/manual acceptance criteria.
- `08_OPERATIONS_AND_USAGE.md` — user operations and research behavior.
- `09_DECISIONS_AND_FUTURE.md` — rationale, non-goals, carefully scoped future options.
- `SOURCES.md` — official sources and researched version notes.
- `prompts/build-this-project.md` — starter prompt to hand the implementation agent.
- `prompts/temporary-web-access.md` — task-level temporary authorization prompt.
- `prompts/comprehensive-web-research.md` — comprehensive research prompt.
- `prompts/mcp-tool-policy.md` — compact optional MCP policy text.
- `skills/web-research/SKILL.md` — optional generic WebX usage skill template.
