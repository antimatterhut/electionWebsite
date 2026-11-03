"""`python -m senate.cli run --stage <name> [--as-of YYYY-MM-DD]` (plan §8.1)."""
from __future__ import annotations

import argparse
import sys

import structlog


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="senate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--stage", required=True, choices=["fetch"])
    run.add_argument("--as-of", default=None)
    args = ap.parse_args(argv)
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.dev.ConsoleRenderer()])
    if args.stage == "fetch":
        from .stages import run_fetch

        return run_fetch()
    return 2


if __name__ == "__main__":
    sys.exit(main())
