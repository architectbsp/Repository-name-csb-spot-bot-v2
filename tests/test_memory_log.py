"""Sprint 12 -- in-memory ring buffer for the live bot-log panel."""

import logging

from app.core.services.memory_log import MemoryLogHandler, get_memory_log_handler


def test_memory_log_handler_keeps_only_the_most_recent_records():
    handler = MemoryLogHandler(capacity=3)
    logger = logging.getLogger("test.memory_log.capacity")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for i in range(5):
        logger.info("line-%d", i)

    recent = handler.recent()
    assert [r.message for r in recent] == ["line-2", "line-3", "line-4"]


def test_memory_log_handler_maps_levels_for_the_ui():
    handler = MemoryLogHandler(capacity=10)
    logger = logging.getLogger("app.core.exchange.binance")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.info("connected")
    logger.warning("rate limited")
    logger.error("rejected")

    levels = [r.level for r in handler.recent()]
    assert "API" in levels or "INFO" in levels
    assert "WARNING" in levels
    assert "ERROR" in levels


def test_get_memory_log_handler_is_a_singleton():
    a = get_memory_log_handler()
    b = get_memory_log_handler()
    assert a is b
