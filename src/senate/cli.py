"""`python -m senate.cli run --stage <name> [--as-of YYYY-MM-DD]` (plan §8.1)."""
from __future__ import annotations

import argparse
import json
import sys

import structlog

log = structlog.get_logger()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="senate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--stage", required=True, choices=["fetch", "model", "backtest", "ei", "crosstab", "county", "ei-validate", "county-backtest", "earlyvote", "earlyvote-backtest", "turnout", "sim"])
    run.add_argument("--as-of", default=None)
    args = ap.parse_args(argv)
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.dev.ConsoleRenderer()])
    if args.stage == "fetch":
        from .stages import run_fetch

        return run_fetch()
    if args.stage == "model":
        from datetime import date

        from .config import load_config
        from .run_model import run_model

        cfg = load_config()
        run_model(cfg, date.fromisoformat(args.as_of) if args.as_of else None)
        return 0
    if args.stage == "backtest":
        from .backtest.run_backtest import run_backtest

        run_backtest()
        return 0
    if args.stage == "ei":
        from .config import load_config
        from .ei.run_state import run_all
        from .ei.shift_ei import run_shift

        cfg = load_config()
        run_all(cfg)
        run_shift(cfg)
        return 0
    if args.stage == "crosstab":
        from .crosstab.run_group_swing import run_group_swing

        run_group_swing()
        return 0
    if args.stage == "county":
        from .county.run_county import run_county

        run_county()
        return 0
    if args.stage == "ei-validate":
        from .ei.validation import run_validation

        _, fails = run_validation()
        if fails:
            log.error("ei_validation_failed", groups=fails)
            return 1
        return 0
    if args.stage == "county-backtest":
        from .county.backtest import run_county_backtest

        print(run_county_backtest())
        return 0
    if args.stage == "earlyvote":
        from .earlyvote.run_earlyvote import run_earlyvote

        print(run_earlyvote().to_string())
        return 0
    if args.stage == "earlyvote-backtest":
        from .earlyvote.backtest import run_earlyvote_backtest

        print(run_earlyvote_backtest())
        return 0
    if args.stage == "turnout":
        from .turnout.run_turnout import run_turnout

        print(run_turnout().to_string())
        return 0
    if args.stage == "sim":
        from .sim.run_sim import run_sim

        out = run_sim()
        print(json.dumps(out["sim"]["seats"], indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
