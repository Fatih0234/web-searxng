#!/usr/bin/env python3
"""
Extraction corpus benchmark — draft for v1.2 experiment #2.

Stratifies 50-100 URLs: official docs, blogs, GitHub pages, docs frameworks, SPAs, PDFs.
Compares:
  - Trafilatura (current)
  - Trafilatura + html2txt fallback (current fallback)
  - Jina Reader (remote, for comparison)
  - Playwright -> Readability/Markdown (future)

Measures: useful-extraction rate, missing code/tables, p50/p95 latency, incremental gain from rendering.

Usage:
  uv run python scripts/bench_extraction.py --corpus scripts/corpus_example.json --output bench.json
  # or just run the built-in tiny corpus (3 URLs) for smoke:
  uv run python scripts/bench_extraction.py --smoke

Notes:
  - This is a harness stub — fill `CORPUS` with your 50-100 URLs and run.
  - Requires `webx` and optionally `trafilatura`; Jina/Playwright are optional remote benchmarks.
"""

from __future__ import annotations
import argparse, json, time, statistics, pathlib

# Tiny smoke corpus — stratify later
SMOKE_CORPUS = [
    {"url": "https://example.com", "type": "docs", "expect": "This domain is for use"},
    {"url": "https://en.wikipedia.org/wiki/Python_(programming_language)", "type": "docs", "expect": "Python"},
    {"url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf", "type": "pdf", "expect": "Dummy PDF"},
]

def bench_one(url: str, max_chars=40000):
    from webx.config import WebXConfig
    from webx.reader import WebReader
    cfg = WebXConfig(
        runtime_dir=pathlib.Path("/tmp/webx-bench-extraction"),
        searxng_url="http://127.0.0.1:8888",
        docker_cmd="docker",
        startup_timeout=30,
        search_timeout=15,
        read_timeout=15,
        max_response_bytes=10*1024*1024,
        max_read_chars=max_chars,
        mcp_stop_on_exit=True,
    )
    r = WebReader(cfg)
    t0 = time.monotonic()
    try:
        resp = r.read(url, no_cache=True)
        elapsed = time.monotonic() - t0
        return {
            "ok": True,
            "engine": resp.engine,
            "chars": resp.characters,
            "truncated": resp.truncated,
            "pages_total": getattr(resp, "pages_total", None),
            "elapsed": elapsed,
            "content_snip": resp.content[:200],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsed": time.monotonic()-t0}

def run_corpus(corpus):
    rows = []
    for entry in corpus:
        url = entry["url"]
        print(f"bench {entry['type']:10} {url} ...", end=" ", flush=True)
        out = bench_one(url)
        expect = entry.get("expect", "")
        useful = out.get("ok") and expect.lower() in out.get("content_snip","").lower() if expect else out.get("ok")
        out["useful"] = bool(useful)
        out["url"] = url
        out["type"] = entry["type"]
        print(f"{'useful' if useful else 'MISS' if out['ok'] else 'ERR'} {out['elapsed']:.2f}s engine={out.get('engine')}")
        rows.append(out)
        time.sleep(0.3)  # be nice
    return rows

def summarize(rows):
    ok = sum(1 for r in rows if r["ok"])
    useful = sum(1 for r in rows if r.get("useful"))
    elapsed = [r["elapsed"] for r in rows if "elapsed" in r]
    p50 = statistics.median(elapsed) if elapsed else 0
    p95 = sorted(elapsed)[int(len(elapsed)*0.95)] if elapsed else 0
    print("\n=== Summary ===")
    print(f"total {len(rows)} ok {ok} useful {useful} useful_rate {useful/max(1,len(rows)):.2%}")
    print(f"p50 {p50:.2f}s p95 {p95:.2f}s")
    by_engine = {}
    for r in rows:
        by_engine.setdefault(r.get("engine","?"), []).append(r)
    for eng, lst in by_engine.items():
        print(f" engine {eng}: {len(lst)}")
    return {"total": len(rows), "ok": ok, "useful": useful, "p50": p50, "p95": p95}

def main():
    ap = argparse.ArgumentParser(description="Extraction benchmark harness")
    ap.add_argument("--corpus", type=str, help="JSON file with list of {url,type,expect}")
    ap.add_argument("--output", type=str, default="bench_extraction.json", help="output JSON")
    ap.add_argument("--smoke", action="store_true", help="run tiny smoke corpus (3 URLs)")
    args = ap.parse_args()

    if args.smoke or not args.corpus:
        corpus = SMOKE_CORPUS
        print("Using smoke corpus (3 URLs). Provide --corpus for full 50-100.")
    else:
        corpus = json.loads(pathlib.Path(args.corpus).read_text())

    rows = run_corpus(corpus)
    summ = summarize(rows)
    out = {"corpus": corpus, "rows": rows, "summary": summ}
    pathlib.Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.output}")

if __name__ == "__main__":
    main()
