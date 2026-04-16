"""Logging configuration for TMS automation bot."""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional
from datetime import datetime


class MillisecondFormatter(logging.Formatter):
    """Custom formatter that includes milliseconds in timestamps."""
    
    @staticmethod
    def _shorten_logger_name(logger_name: str) -> str:
        """Return a compact logger name for log output."""
        if logger_name.startswith("main."):
            return logger_name.split(".")[-1]
        return logger_name

    def formatTime(self, record, datefmt=None):
        """Override to include milliseconds."""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%H:%M:%S")
        # Add milliseconds
        s = f"{s}.{int(record.msecs):03d}"
        return s

    def format(self, record):
        """Format log record with shortened logger name."""
        original_name = record.name
        record.name = self._shorten_logger_name(original_name)

        try:
            return super().format(record)
        finally:
            record.name = original_name

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }

    def formatTime(self, record, datefmt=None):
        """Override to include milliseconds."""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%H:%M:%S")
        # Add milliseconds
        s = f"{s}.{int(record.msecs):03d}"
        return s

    def format(self, record):
        """Format log record with colors."""
        # Save original levelname
        original_levelname = record.levelname

        # Add color to level name
        if original_levelname in self.COLORS:
            record.levelname = f"{self.COLORS[original_levelname]}{original_levelname}{self.COLORS['RESET']}"

        # Format the message
        result = super().format(record)

        # Restore original levelname so other formatters don't get colored version
        record.levelname = original_levelname

        return result


def setup_logger(
    name: str = 'main',
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    console_output: bool = True,
    log_root: str = "logs",
) -> logging.Logger:
    """
    Set up a logger with both file and console handlers.

    Args:
        name: Logger name
        log_file: Path to log file (optional)
        level: Logging level
        console_output: Whether to output to console

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    # Create formatters
    file_formatter = MillisecondFormatter(
        '%(asctime)s | %(levelname)-7s | %(threadName)-12s | %(message)s',
        datefmt='%H:%M:%S'
    )

    console_formatter = ColoredFormatter(
        '%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # File handler (if log file specified)
    if log_file:
        log_file = (
            f"{log_root}/{datetime.now().strftime('%Y%m%d')}/"
            + log_file.replace('.log', f'_{datetime.now().strftime("%H%M%S")}.log')
        )
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8',
            delay=True,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'main') -> logging.Logger:
    """
    Get the shared application logger.

    The project uses a single configured logger instance. Module-specific names
    are intentionally not attached here, so handler level and formatting stay
    consistent regardless of call site.

    Args:
        name: Ignored. Kept for compatibility with existing call sites.

    Returns:
        Logger instance
    """
    root_logger = logging.getLogger('main')

    has_file_handler = any(
        isinstance(h, RotatingFileHandler) for h in root_logger.handlers
    )

    if not has_file_handler:
        root_logger.handlers.clear()
        setup_logger('main', log_file='tms_automation.log')

    return root_logger


def get_user_logger(user_id: str, log_dir: str = 'logs') -> logging.Logger:
    """
    Get a user-specific logger.

    Args:
        user_id: User identifier
        log_dir: Directory for log files

    Returns:
        User-specific logger instance
    """
    logger_name = f'main.user.{user_id}'
    log_file = Path(log_dir) / f'{user_id}.log'

    return setup_logger(
        name=logger_name,
        log_file=str(log_file),
        level=logging.INFO,
        console_output=True
    )


def detach_console_handlers(name: str = "main") -> list[logging.Handler]:
    """Remove stream handlers from a logger and return them for later restoration."""
    logger = logging.getLogger(name)
    detached: list[logging.Handler] = []
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            logger.removeHandler(handler)
            detached.append(handler)
    return detached


def attach_handlers(name: str, handlers: list[logging.Handler]) -> None:
    """Reattach previously detached handlers to a logger."""
    logger = logging.getLogger(name)
    for handler in handlers:
        if handler not in logger.handlers:
            logger.addHandler(handler)


# Default logger instance - removed to prevent initialization without file handler
# Use get_logger() or setup_logger() explicitly instead
# default_logger = setup_logger()
