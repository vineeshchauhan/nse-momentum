"""
Entry point — initialises DB, then starts the APScheduler.

Usage:
    python main.py
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


def main():
    from db.models import create_tables
    logger.info("Initialising database tables...")
    create_tables()

    from scheduler import build_scheduler
    scheduler = build_scheduler()

    logger.info("Scheduler starting. Press Ctrl+C to stop.")
    for job in scheduler.get_jobs():
        logger.info(f"  Registered: {job.name} -> trigger: {job.trigger}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
