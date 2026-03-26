"""
Shared logging utilities for Contexa.

All components should use `get_logger(__name__)` to get a structlog logger.
The logging configuration is set up once by the daemon at startup via
`contexa.daemon._configure_logging()`.

Usage:
    from contexa.logging import get_logger
    log = get_logger(__name__)
    log.info("something happened", key="value")
    log.error("something failed", error=str(exc), exc_info=True)
"""

from __future__ import annotations

import logging
import sys
import traceback

import structlog


def get_logger(name: str = "contexa"):
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)


def log_unhandled_error(logger, exc: Exception, context: str = "") -> None:
    """Log an unhandled exception with full stack trace at ERROR level.

    Args:
        logger: A structlog logger instance.
        exc: The exception to log.
        context: Optional description of where the error occurred.
    """
    tb = traceback.format_exc()
    logger.error(
        "Unhandled error",
        context=context,
        error=str(exc),
        error_type=type(exc).__name__,
        traceback=tb,
    )


def install_global_exception_handler() -> None:
    """Install a global exception handler that logs unhandled exceptions.

    Called once during daemon startup. Ensures any uncaught exception
    is logged at ERROR level with a full stack trace before the process exits.
    """
    log = get_logger("contexa.unhandled")

    def _handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_tb(exc_tb))
        log.error(
            "Unhandled exception",
            error_type=exc_type.__name__,
            error=str(exc_value),
            traceback=tb_str,
        )

    sys.excepthook = _handler
