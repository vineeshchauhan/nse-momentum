"""
Central logging configuration. Call setup_logging() once at application startup.
Safe to call multiple times — logging.basicConfig() is a no-op if handlers already exist.
"""
import logging
import os
import sys


def setup_logging(log_file: str = "logs/trading.log") -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("SmartApi").setLevel(logging.WARNING)
    # Suppress werkzeug's access log — we emit our own in web/app.py
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
