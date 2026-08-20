#!/usr/bin/env python3
"""
Search benchmark — draft for v1.2 experiment #3.

Compares pinned SearXNG vs Brave (or other hosted) on ~50 coding queries.
Scores: top-5 primary-source hit rate, zero-result/error rate, latency, cost.

Usage:
  # SearXNG only (default):
  uv run python scripts/bench_search.py --smoke
  # With Brave (requires BRAVE_API_KEY):
  BRAVE_API_KEY=... uv run python scripts/bench_search.py --backend brave --corpus scripts/search_corpus.json

Corpus format: JSON list of {query, expect_domain?} e.g. {"query": "SearXNG documentation", "expect": "docs.searxng.org"}

Notes:
  - This is a harness stub — fill with 50 representative coding queries before deciding.
  - Keep agent schema provider-neutral; Brave is explicit opt-in via WEBX_SEARCH_BACKEND env, not silent fallback.
"""

from __future__ import annotations
import argparse, json, time, pathlib, statistics, os

SMOKE_QUERIES = [
    {"query": "SearXNG documentation", "expect": "docs.searxng.org"},
    {"query": "Python httpx documentation", "expect": "python-httpx.org"},
    {"query": "trafilatura python library", "expect": "trafilatura"},
    {"query": "pypdf extract text", "expect": "pypdf"},
    {"query": "docker compose healthcheck", "expect": "docs.docker.com"},
]

def search_searxng(query: str, limit=5):
    from webx.config import WebXConfig
    from webx.core import WebX
    cfg = WebXConfig(
        runtime_dir=pathlib.Path("/tmp/webx-bench-search"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10*1024*1024,
        max_read_chars=40000,
        mcp_stop_on_exit=True,
    )
    core = WebX(cfg)
    t0 = time.monotonic()
    try:
        resp = core.search(query=query, limit=limit)
        elapsed = time.monotonic() - t0
        return {
            "ok": True,
            "count": len(resp.results),
            "top_urls": [r.url for r in resp.results[:5]],
            "top_titles": [r.title for r in resp.results[:5]],
            "elapsed": elapsed,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsed": time.monotonic()-t0}

def score_primary_hit(top_urls, expect_domain):
    if not expect_domain:
        return None
    for u in top_urls:
        if expect_domain.lower() in u.lower():
            return True
    return False

def run_bench(queries, limit=5, backend="searxng"):
    rows = []
    for q in queries:
        query = q["query"]
        expect = q.get("expect")
        print(f"search [{backend:8}] {query!r:40} ...", end=" ", flush=True)
        if backend == "searxng":
            out = search_searxng(query, limit=limit)
        elif backend == "brave":
            # Stub: implement BraveSearchBackend when built
            out = {"ok": False, "error": "brave backend not yet implemented (see TODO-03e1f585)", "elapsed": 0}
        else:
            out = {"ok": False, "error": f"unknown backend {backend}", "elapsed": 0}
        out["query"] = query
        out["expect"] = expect
        out["primary_hit"] = score_primary_hit(out.get("top_urls", []), expect)
        hit = out["primary_hit"]
        status = "HIT" if hit else "MISS" if hit is False and out["ok"] else "ERR" if not out["ok"] else "ok"
        print(f"{status} {out['elapsed']:.2f}s count={out.get('count','?')}")
        rows.append(out)
        time.sleep(0.6)
    return rows

def summarize(rows):
    ok = sum(1 for r in rows if r["ok"])
    hits = sum(1 for r in rows if r["primary_hit"] is True)
    scored = sum(1 for r in rows if r["primary_hit"] is not None)
    zero = sum(1 for r in rows if r.get("count")==0)
    elapsed = [r["elapsed"] for r in rows if "elapsed" in r]
    p50 = statistics.median(elapsed) if elapsed else 0
    print("\n=== Summary ===")
    print(f"total {len(rows)} ok {ok} zero {zero} primary_hit {hits}/{scored} ({hits/max(1,scored):.1%}) p50 {p50:.2f}s")
    return {"total": len(rows), "ok": ok, "zero": zero, "hits": hits, "scored": scored, "p50": p50}

def main():
    ap = argparse.ArgumentParser(description="Search benchmark harness")
    ap.add_argument("--corpus", type=str, help="JSON list of {query, expect}")
    ap.add_argument("--output", type=str, default="bench_search.json")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--backend", type=str, default="searxng", choices=["searxng","brave"])
    ap.add_argument("--smoke", action="store_true", help="run 5 smoke queries")
    args = ap.parse_args()

    if args.smoke or not args.corpus:
        queries = SMOKE_QUERIES
        print("Using smoke queries (5). Provide --corpus for full 50.")
    else:
        queries = json.loads(pathlib.Path(args.corpus).read_text())

    rows = run_bench(queries, limit=args.limit, backend=args.backend)
    summ = summarize(rows)
    out = {"backend": args.backend, "queries": queries, "rows": rows, "summary": summ}
    pathlib.Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.output}")
    # Cost hint for Brave
    if args.backend == "brave":
        print("Brave cost: $5/1k requests, 50 QPS (https://brave.com/search/api/)")

if __name__ == "__main__":
    main()
