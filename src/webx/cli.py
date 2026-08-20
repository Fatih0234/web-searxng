"""CLI frontend — thin adapter, stdout=data, stderr=diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .config import get_config
from .errors import WebXError


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webx",
        description="Local on-demand web search for coding agents",
    )
    p.add_argument("--version", action="version", version=f"webx {__version__}")
    p.add_argument("--verbose", action="store_true", help="enable verbose diagnostics")

    sub = p.add_subparsers(dest="command")

    # init
    sp = sub.add_parser("init", help="materialize runtime assets and secret")
    sp.add_argument("--force-templates", action="store_true", help="replace compose/settings templates but preserve secret")
    sp.add_argument("--show-path", action="store_true", help="print runtime path")

    # doctor
    sub.add_parser("doctor", help="check runtime, docker, SearXNG reachability")

    # up
    sub.add_parser("up", help="ensure SearXNG is running")

    # stop
    sub.add_parser("stop", help="stop SearXNG (compose stop)")
    # status
    sp = sub.add_parser("status", help="show runtime status")
    sp.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    # logs
    sp = sub.add_parser("logs", help="show compose logs")
    sp.add_argument("--tail", type=int, default=100, help="number of lines")

    # search
    sp = sub.add_parser("search", help="search the web via local SearXNG")
    sp.add_argument("query", help="search query")
    sp.add_argument("--limit", type=int, default=8, help="max results (default 8, cap 50)")
    sp.add_argument("--category", default="general", help="search category")
    sp.add_argument("--language", default=None, help="language code")
    sp.add_argument("--page", type=int, default=1, help="page number")
    sp.add_argument("--time", dest="time_range", choices=["day", "month", "year"], default=None, help="time range")
    sp.add_argument("--safe-search", type=int, choices=[0, 1, 2], default=None, dest="safe_search", help="safe search level")
    sp.add_argument("--engine", action="append", dest="engines", default=None, help="engine name (repeatable)")
    sp.add_argument("--pretty", action="store_true", help="pretty-print JSON")

    # read
    sp = sub.add_parser("read", help="fetch and extract a URL")
    sp.add_argument("url", help="URL to read")
    sp.add_argument("--max-chars", type=int, default=None, dest="max_chars", help="max extracted chars")
    sp.add_argument("--json", action="store_true", dest="json_output", help="JSON envelope")
    sp.add_argument("--links", action="store_true", help="preserve links")
    sp.add_argument("--no-tables", action="store_true", help="omit tables")
    sp.add_argument("--precision", action="store_true", help="favor precision")
    sp.add_argument("--recall", action="store_true", help="favor recall")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # no subcommand -> show help
    if args.command is None:
        parser.print_help()
        return 0

    verbose = getattr(args, "verbose", False)

    try:
        return _dispatch(args, verbose)
    except WebXError as e:
        print(f"error: {e}", file=sys.stderr)
        if e.hint:
            print(f"hint: {e.hint}", file=sys.stderr)
        if verbose:
            import traceback

            traceback.print_exc(file=sys.stderr)
        return e.exit_code
    except SystemExit:
        raise
    except Exception as e:  # unexpected
        print(f"error: {e}", file=sys.stderr)
        if verbose:
            import traceback

            traceback.print_exc(file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace, verbose: bool) -> int:
    # lazy imports to keep help fast
    if args.command == "init":
        from .lifecycle import init_runtime

        cfg = get_config()
        result = init_runtime(cfg, force_templates=args.force_templates, show_path=args.show_path, verbose=verbose)
        # result printed inside init_runtime
        return 0

    if args.command == "doctor":
        from .lifecycle import doctor

        cfg = get_config()
        report = doctor(cfg)
        # human readable to stderr? but we keep simple: JSON if verbose? spec says doctor is inspection, human readable.
        # Print human summary to stdout
        print(f"webx {__version__}")
        print(f"runtime: {report.runtime_dir} ({'initialized' if report.initialized else 'not initialized'})")
        print(f"docker: {'available' if report.docker_available else 'unavailable'}" + (f" ({report.compose_version})" if report.compose_version else ""))
        if report.docker_error:
            print(f"docker error: {report.docker_error}", file=sys.stderr)
        print(f"templates: {'present' if report.templates_present else 'missing'}")
        print(f"SearXNG url: {report.searxng_url} reachable={report.searxng_reachable}")
        print(f"trafilatura: {report.trafilatura_version or 'missing'}")
        print(f"mcp: {report.mcp_version or ('not installed' if not report.mcp_available else 'available')}")
        for note in report.notes:
            print(f"note: {note}")
        return 0

    if args.command == "up":
        from .lifecycle import ensure_running

        cfg = get_config()
        status = ensure_running(cfg, verbose=verbose)
        print(f"SearXNG running at {cfg.searxng_url}", file=sys.stderr)
        return 0

    if args.command == "stop":
        from .lifecycle import compose_stop

        cfg = get_config()
        compose_stop(cfg, verbose=verbose)
        print("SearXNG stopped", file=sys.stderr)
        return 0

    if args.command == "status":
        from .lifecycle import status as get_status

        cfg = get_config()
        st = get_status(cfg)
        if args.json_output:
            print(json.dumps(st.to_dict()))
        else:
            print(f"initialized: {st.initialized}")
            print(f"compose: {'present' if st.compose_exists else 'missing'}")
            print(f"docker: {'available' if st.docker_available else 'unavailable'}")
            print(f"SearXNG running: {st.searxng_running}")
            print(f"url: {st.url}")
            print(f"runtime: {st.runtime_dir}")
            # Hint when global container from other WEBX_DATA_DIR is running but local compose missing
            if st.searxng_running and not st.compose_exists:
                print("note: SearXNG is running but local compose.yml missing — global container from another WEBX_DATA_DIR (single webx-searxng name shared)", file=sys.stderr)
        return 0

    if args.command == "logs":
        from .lifecycle import compose_logs

        cfg = get_config()
        logs = compose_logs(cfg, tail=args.tail, verbose=verbose)
        print(logs)
        return 0

    if args.command == "search":
        from .core import WebX

        cfg = get_config()
        core = WebX(cfg)
        # hard cap per spec
        limit = args.limit
        if limit < 1 or limit > 50:
            print("error: --limit must be between 1 and 50", file=sys.stderr)
            return 2
        if args.page < 1:
            print("error: --page must be >=1", file=sys.stderr)
            return 2
        resp = core.search(
            query=args.query,
            limit=limit,
            category=args.category,
            language=args.language,
            page=args.page,
            time_range=args.time_range,
            safe_search=args.safe_search,
            engines=args.engines,
        )
        out = resp.to_dict()
        if args.pretty:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(out, ensure_ascii=False))
        return 0

    if args.command == "read":
        from .core import WebX

        cfg = get_config()
        core = WebX(cfg)
        max_chars = args.max_chars if args.max_chars is not None else cfg.max_read_chars
        # hard cap per spec: at least respect config's upper bound
        if max_chars < 1000 or max_chars > 500000:
            print("error: --max-chars out of range (1000-500000)", file=sys.stderr)
            return 2
        # verbose timing — keep library pure, measure in CLI
        t0 = time.monotonic() if verbose else None
        # mutually exclusive precision/recall? not required
        resp = core.read(
            url=args.url,
            max_chars=max_chars,
            include_links=args.links,
            include_tables=not args.no_tables,
            precision=args.precision,
            recall=args.recall,
        )
        if verbose and t0 is not None:
            elapsed = time.monotonic() - t0
            print(
                f"read ok: {resp.final_url} {resp.content_type or 'unknown'} {resp.characters} chars engine={resp.engine or 'unknown'} {elapsed:.2f}s",
                file=sys.stderr,
            )
        if args.json_output:
            print(json.dumps(resp.to_dict(), ensure_ascii=False))
        else:
            # default: content only on stdout
            print(resp.content)
        return 0

    parser = _build_parser()
    parser.print_help()
    return 2
