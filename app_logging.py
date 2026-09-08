"""Private, local diagnostics suitable for sharing with application support."""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_version import APP_NAME, APP_VERSION

LOGGER_NAME = "accessible_reels"
LOG_FILE_NAME = "accessible-reels.log"
_URL_QUERY = re.compile(r"(https?://[^\s'\"]+?)(?:[?#][^\s'\"]*)?(?=[\s'\"]|$)", re.IGNORECASE)
_SECRET = re.compile(r"(?i)\b(cookie|token|authorization|password|secret)\b\s*([=:])\s*[^\s,;]+")


def log_directory(local_app_data: str | Path | None = None) -> Path:
    """Return the per-user directory for diagnostic logs."""
    root = Path(local_app_data or os.environ.get("LOCALAPPDATA") or Path.home())
    return root / APP_NAME / "logs"


def sanitize(value: object) -> str:
    """Remove URL query data and common credential fields from a log message."""
    text = _URL_QUERY.sub(r"\1", str(value))
    return _SECRET.sub(r"\1=***", text)


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return sanitize(super().format(record))


def configure_logging(*, local_app_data: str | Path | None = None) -> Path | None:
    """Configure a small rotating diagnostic log and return its path."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                return Path(handler.baseFilename)
        return None
    try:
        directory = log_directory(local_app_data)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILE_NAME
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(_SafeFormatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
        logger.addHandler(handler)
        logger.info("Application starting: version=%s python=%s platform=%s", APP_VERSION, sys.version.split()[0], sys.platform)
        return path
    except OSError:
        return None


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def install_exception_logging() -> None:
    """Persist unexpected main- and worker-thread failures before Python reports them."""
    logger = get_logger()
    previous = sys.excepthook

    def report(exception_type, value, traceback):
        logger.error("Unhandled exception", exc_info=(exception_type, value, traceback))
        previous(exception_type, value, traceback)

    sys.excepthook = report
    if hasattr(threading, "excepthook"):
        previous_thread = threading.excepthook

        def report_thread(args):
            logger.error("Unhandled worker exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            previous_thread(args)

        threading.excepthook = report_thread
