"""Dataclass models per 03_CORE_SPEC — kept lightweight, no validation framework."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchQuery:
    query: str
    limit: int = 8
    category: str | None = "general"
    language: str | None = None
    page: int = 1
    time_range: str | None = None  # day | month | year
    safe_search: int | None = None  # 0 | 1 | 2
    engines: list[str] | None = None


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    engines: list[str] = field(default_factory=list)
    score: float = 0.0
    category: str = "general"
    published_date: str | None = None


@dataclass(slots=True)
class SearchMeta:
    result_count: int
    page: int = 1
    category: str = "general"
    time_range: str | None = None


@dataclass(slots=True)
class SearchResponse:
    query: str
    results: list[SearchResult]
    meta: SearchMeta

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "engines": r.engines,
                    "score": r.score,
                    "category": r.category,
                    "published_date": r.published_date,
                }
                for r in self.results
            ],
            "meta": {
                "result_count": self.meta.result_count,
                "page": self.meta.page,
                "category": self.meta.category,
                "time_range": self.meta.time_range,
            },
        }


@dataclass(slots=True)
class ReadRequest:
    url: str
    max_chars: int = 40000
    include_links: bool = False
    include_tables: bool = True
    precision: bool = False
    recall: bool = False


@dataclass(slots=True)
class ReadResponse:
    url: str
    final_url: str
    title: str | None
    content_type: str | None
    content: str
    truncated: bool
    characters: int
    # optional extra metadata, kept backward-compatible
    engine: str | None = None  # trafilatura vs fallback

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "content_type": self.content_type,
            "content": self.content,
            "truncated": self.truncated,
            "characters": self.characters,
        }


@dataclass(slots=True)
class RuntimeStatus:
    initialized: bool
    docker_available: bool
    searxng_running: bool
    url: str
    runtime_dir: str
    compose_exists: bool = False

    def to_dict(self) -> dict:
        return {
            "initialized": self.initialized,
            "docker_available": self.docker_available,
            "searxng_running": self.searxng_running,
            "url": self.url,
            "runtime_dir": self.runtime_dir,
            "compose_exists": self.compose_exists,
        }


@dataclass(slots=True)
class DoctorReport:
    python_version: str
    package_version: str
    runtime_dir: str
    initialized: bool
    docker_available: bool
    compose_available: bool
    compose_version: str | None
    templates_present: bool
    searxng_url: str
    searxng_reachable: bool
    trafilatura_version: str | None
    mcp_available: bool
    mcp_version: str | None
    docker_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "package_version": self.package_version,
            "runtime_dir": self.runtime_dir,
            "initialized": self.initialized,
            "docker_available": self.docker_available,
            "compose_available": self.compose_available,
            "compose_version": self.compose_version,
            "templates_present": self.templates_present,
            "searxng_url": self.searxng_url,
            "searxng_reachable": self.searxng_reachable,
            "trafilatura_version": self.trafilatura_version,
            "mcp_available": self.mcp_available,
            "mcp_version": self.mcp_version,
            "docker_error": self.docker_error,
            "notes": self.notes,
        }
