"""Serve the local project dashboard with Python's standard library."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .build_data import ROOT, write_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    dashboard = ROOT / "dashboard"
    if not args.no_build:
        write_bundle()
    def handler(*handler_args: object, **handler_kwargs: object) -> SimpleHTTPRequestHandler:
        return SimpleHTTPRequestHandler(
            *handler_args, directory=str(dashboard), **handler_kwargs
        )

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
