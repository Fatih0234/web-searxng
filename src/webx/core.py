"""Core facade — shared by CLI and MCP. Stub for Phase 1."""

from __future__ import annotations

from .config import WebXConfig
from .models import ReadResponse, SearchResponse


class WebX:
    """Small API that both frontends call."""

    def __init__(self, config: WebXConfig) -> None:
        self.config = config

    def search(self, query: str, limit: int = 8, category: str | None = "general", language: str | None = None, page: int = 1, time_range: str | None = None, safe_search: int | None = None, engines: list[str] | None = None) -> SearchResponse:
        from .searxng import SearxngClient

        client = SearxngClient(self.config)
        return client.search(query, limit, category, language, page, time_range, safe_search, engines)

    def read(self, url: str, max_chars: int = 40000, include_links: bool = False, include_tables: bool = True, precision: bool = False, recall: bool = False, verbose: bool = False, no_cache: bool = False) -> ReadResponse:
        from .reader import WebReader

        reader = WebReader(self.config)
        # verbose is handled in cli layer to keep library pure for MCP; accept for forward-compat
        _ = verbose
        return reader.read(url, max_chars, include_links, include_tables, precision, recall, no_cache=no_cache)

    def start_search_service(self):
        from .lifecycle import ensure_running

        return ensure_running(self.config)

    def stop_search_service(self):
        from .lifecycle import compose_stop

        compose_stop(self.config)
        from .lifecycle import status

        return status(self.config)

    def status(self):
        from .lifecycle import status

        return status(self.config)

    def doctor(self):
        from .lifecycle import doctor

        return doctor(self.config)
