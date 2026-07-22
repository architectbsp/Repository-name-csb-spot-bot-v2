"""
Central application logging configuration.

Historically this project had no logging setup at all: modules called
`logging.getLogger(__name__)` but nothing ever attached a handler, so any
file logging that existed came from ad-hoc shell redirection (`> bot.log`)
which grows forever and is never rotated (see docs risk B32). This module
gives every logger in the app a single, size-bounded log file plus a
console handler, configured once at process startup.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# app/core/logging_config.py -> app/core -> app -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_LOG_DIR = _PROJECT_ROOT / "logs"
DEFAULT_LOG_FILE_NAME = "bot.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 5

_configured = False


def configure_logging(
    *,
    level: int = logging.INFO,
    log_dir: str | Path | None = None,
    log_file_name: str = DEFAULT_LOG_FILE_NAME,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    force: bool = False,
) -> None:
    """
    Configures the root logger with a rotating file handler and a console
    handler.

    A `RotatingFileHandler` caps `logs/bot.log` at `max_bytes` (default
    10 MB); once exceeded it is rolled over into `bot.log.1` .. up to
    `bot.log.<backup_count>` (default 5), so disk usage never grows
    unbounded the way a plain shell-redirected log file does.

    Idempotent by default (safe to import/call from multiple entry
    points, e.g. main.py and test fixtures); pass `force=True` to
    reconfigure (mainly useful in tests).
    """
    global _configured

    if _configured and not force:
        return

    directory = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        directory / log_file_name,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _configured = True


def is_configured() -> bool:
    return _configured
