import logging
from db.connection import get_cursor

logger = logging.getLogger(__name__)


def log_run(job_id, job_name, status, started_at, finished_at,
            error_msg=None, num_signals=None, email_sent=False):
    duration = (finished_at - started_at).total_seconds() if finished_at else None
    try:
        with get_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO scheduler_runs
                    (job_id, job_name, started_at, finished_at, status,
                     error_msg, duration_s, num_signals, email_sent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (job_id, job_name, started_at, finished_at, status,
                  error_msg, duration, num_signals, email_sent))
    except Exception as e:
        logger.error(f"Failed to write scheduler_runs: {e}")
