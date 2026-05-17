"""
APScheduler configuration.

Jobs:
  - Daily 6:00 PM IST   → data_pipeline.daily_batch.run()
  - Weekdays 3:00 PM IST → strategies.btst.run() + send email
  - Monday 9:00 AM IST  → strategies.momentum.run() + send email
"""
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import TIMEZONE

logger = logging.getLogger(__name__)
IST = pytz.timezone(TIMEZONE)


def job_daily_batch():
    from data_pipeline.daily_batch import run
    run()


def job_btst():
    from strategies.btst import run as btst_run
    from emailer.sender import send_btst_email
    signals = btst_run()
    if signals:
        send_btst_email(signals)
    else:
        logger.info("No BTST signals — email not sent.")


def job_momentum():
    from strategies.momentum import run as momentum_run
    from emailer.sender import send_momentum_email
    result = momentum_run()
    if result:
        send_momentum_email(
            result["top30"],
            result["changes"],
            result["exits"],
            result["week_start"],
        )


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=IST)

    # Daily OHLCV fetch at 6:00 PM IST (every day)
    scheduler.add_job(
        job_daily_batch,
        CronTrigger(hour=18, minute=0, timezone=IST),
        id="daily_batch",
        name="Daily OHLCV + BTST result update",
        misfire_grace_time=300,
    )

    # BTST screener at 3:00 PM IST, weekdays only
    scheduler.add_job(
        job_btst,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=0, timezone=IST),
        id="btst_screener",
        name="BTST Screener",
        misfire_grace_time=120,
    )

    # Weekly momentum every Monday at 9:00 AM IST
    scheduler.add_job(
        job_momentum,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=IST),
        id="momentum_weekly",
        name="Weekly Momentum Portfolio",
        misfire_grace_time=300,
    )

    return scheduler
