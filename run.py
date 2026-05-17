"""
Manual task runner — execute any scheduled job for any date.

Usage:
    python run.py daily_batch [--date YYYY-MM-DD]
    python run.py btst        [--date YYYY-MM-DD] [--no-email]
    python run.py momentum    [--date YYYY-MM-DD] [--no-email]

If --date is omitted, defaults to today.

Notes:
  daily_batch : Fetches OHLCV from Angel API for the given date, then updates
                BTST next-day results for signals dated the previous day.
  btst        : For past dates, prices are read from the OHLCV table (no live
                API call per stock). Nifty gate still checked via Angel API.
  momentum    : Fully DB-driven; pass any date in the week you want to replay.
"""
import argparse
import logging
import sys
from datetime import date


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}' — expected YYYY-MM-DD")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Manually run a scheduled task for any date.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "task",
        choices=["daily_batch", "btst", "momentum"],
        help="Task to run",
    )
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Run as if today were this date (default: today)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        metavar="SYMBOL",
        help="Test with a single symbol, e.g. IDFCFIRSTB (daily_batch only)",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending the email (btst and momentum only)",
    )
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger(__name__)

    if args.task == "daily_batch":
        from data_pipeline.daily_batch import run
        run(target_date=args.date, symbol=args.symbol)

    elif args.task == "btst":
        from strategies.btst import run as btst_run
        from emailer.sender import send_btst_email
        signals = btst_run(target_date=args.date)
        if not signals:
            log.info("No BTST signals — email not sent.")
        elif args.no_email:
            log.info("--no-email: skipping email.")
        else:
            send_btst_email(signals)

    elif args.task == "momentum":
        from strategies.momentum import run as momentum_run
        from emailer.sender import send_momentum_email
        result = momentum_run(as_of_date=args.date)
        if not result:
            log.warning("Momentum run returned no result.")
        elif args.no_email:
            log.info("--no-email: skipping email.")
        else:
            send_momentum_email(
                result["top30"],
                result["changes"],
                result["exits"],
                result["week_start"],
            )


if __name__ == "__main__":
    main()
