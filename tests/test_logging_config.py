import logging
from logging.handlers import RotatingFileHandler

from app.core import logging_config
from app.core.logging_config import configure_logging


def _reset_root_logger():
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    logging_config._configured = False


def test_configure_logging_adds_rotating_file_handler(tmp_path):
    _reset_root_logger()

    try:
        configure_logging(
            log_dir=tmp_path,
            max_bytes=123,
            backup_count=2,
            force=True,
        )

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, RotatingFileHandler)
        ]

        assert len(file_handlers) == 1
        handler = file_handlers[0]
        assert handler.maxBytes == 123
        assert handler.backupCount == 2
        assert (tmp_path / "bot.log").exists()
    finally:
        _reset_root_logger()


def test_configure_logging_is_idempotent_by_default(tmp_path):
    _reset_root_logger()

    try:
        configure_logging(log_dir=tmp_path, force=True)
        handler_count_after_first = len(logging.getLogger().handlers)

        # Second call without force=True must be a no-op.
        configure_logging(log_dir=tmp_path)

        assert len(logging.getLogger().handlers) == handler_count_after_first
        assert logging_config.is_configured() is True
    finally:
        _reset_root_logger()


def test_configure_logging_caps_log_file_growth_via_rotation(tmp_path):
    _reset_root_logger()

    try:
        configure_logging(
            log_dir=tmp_path,
            max_bytes=200,
            backup_count=1,
            force=True,
        )

        logger = logging.getLogger("test.rotation")

        for _ in range(200):
            logger.info("x" * 50)

        log_file = tmp_path / "bot.log"
        backup_file = tmp_path / "bot.log.1"

        # Rotation must have kicked in: the active file stays small and a
        # rolled-over backup was created, instead of one ever-growing file.
        assert log_file.exists()
        assert log_file.stat().st_size <= 200 + 200  # small margin for one record
        assert backup_file.exists()
    finally:
        _reset_root_logger()
