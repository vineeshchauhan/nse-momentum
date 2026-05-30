"""
APScheduler configuration.

Jobs:
  - Daily 6:00 PM IST   → data_pipeline.daily_batch.run()
  - Weekdays 3:00 PM IST → strategies.btst.run() + send email
  - Saturday 9:00 AM IST → strategies.momentum.run() + send email
"""
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import TIMEZONE

logger = logging.getLogger(__name__)
IST = pytz.timezone(TIMEZONE)


def job_daily_batch():
    from data_pipeline.daily_batch import run
    from db.scheduler_log import log_run
    started = datetime.now(IST)
    try:
        run()
        log_run("daily_batch", "Daily OHLCV + BTST result update",
                "success", started, datetime.now(IST))
    except Exception as e:
        logger.exception("job_daily_batch failed")
        log_run("daily_batch", "Daily OHLCV + BTST result update",
                "failure", started, datetime.now(IST), error_msg=str(e))
        raise


def job_btst():
    from strategies.btst import run as btst_run
    from emailer.sender import send_btst_email
    from db.scheduler_log import log_run
    started = datetime.now(IST)
    signals, email_sent = [], False
    try:
        signals, _ = btst_run()
        if signals:
            email_sent = send_btst_email(signals)
        else:
            logger.info("No BTST signals — email not sent.")
        status = "success" if signals else "skipped"
        log_run("btst_screener", "BTST Screener", status,
                started, datetime.now(IST),
                num_signals=len(signals), email_sent=email_sent)
    except Exception as e:
        logger.exception("job_btst failed")
        log_run("btst_screener", "BTST Screener", "failure",
                started, datetime.now(IST),
                error_msg=str(e), num_signals=len(signals), email_sent=email_sent)
        raise


def job_momentum():
    from strategies.momentum import run as momentum_run
    from emailer.sender import send_momentum_email
    from db.scheduler_log import log_run
    started = datetime.now(IST)
    result, email_sent = {}, False
    try:
        result = momentum_run() or {}
        if result:
            email_sent = send_momentum_email(
                result["top30"],
                result["changes"],
                result["exits"],
                result["week_start"],
            )
        count = len(result.get("top30", []))
        log_run("momentum_weekly", "Weekly Momentum Portfolio", "success",
                started, datetime.now(IST),
                num_signals=count, email_sent=email_sent)
    except Exception as e:
        logger.exception("job_momentum failed")
        log_run("momentum_weekly", "Weekly Momentum Portfolio", "failure",
                started, datetime.now(IST), error_msg=str(e), email_sent=email_sent)
        raise


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

    # Weekly momentum every Saturday at 9:00 AM IST
    scheduler.add_job(
        job_momentum,
        CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=IST),
        id="momentum_weekly",
        name="Weekly Momentum Portfolio",
        misfire_grace_time=300,
    )

    return scheduler
