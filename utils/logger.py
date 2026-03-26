"""Logging configuration for TMS automation bot."""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional
from datetime import datetime


class MillisecondFormatter(logging.Formatter):
    """Custom formatter that includes milliseconds in timestamps."""

    def formatTime(self, record, datefmt=None):
        """Override to include milliseconds."""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        # Add milliseconds
        s = f"{s}.{int(record.msecs):03d}"
        return s


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
    console_output: bool = True
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
        '%(asctime)s | %(name)s | %(levelname)s | %(threadName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_formatter = ColoredFormatter(
        '%(asctime)s | %(levelname)s | %(message)s',
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
        log_file = f'logs/{datetime.now().strftime("%Y%m%d")}/' + log_file.replace('.log', f'_{datetime.now().strftime("%H%M%S")}.log')
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'main') -> logging.Logger:
    """
    Get an existing logger or create a new one.

    This function ensures all loggers write to file by either:
    1. Setting up the root 'main' logger with file handler
    2. Using hierarchical naming so child loggers propagate to root

    Args:
        name: Logger name (e.g., __name__ from calling module)

    Returns:
        Logger instance
    """
    # Ensure the root logger is set up with file handler
    root_logger = logging.getLogger('main')

    # Check if root logger has a file handler
    has_file_handler = any(
        isinstance(h, RotatingFileHandler) for h in root_logger.handlers
    )

    if not has_file_handler:
        # Clear any existing handlers and set up properly with file handler
        root_logger.handlers.clear()
        setup_logger('main', log_file='tms_automation.log')

    # Create hierarchical logger name if not already prefixed
    if name != 'main' and not name.startswith('main.'):
        hierarchical_name = f'main.{name}'
    else:
        hierarchical_name = name

    logger = logging.getLogger(hierarchical_name)

    # For child loggers, ensure propagation is enabled and no duplicate handlers
    if hierarchical_name != 'main':
        logger.propagate = True
        if not logger.level:
            logger.setLevel(logging.DEBUG)  # Let root handle filtering

    return logger


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


# Default logger instance - removed to prevent initialization without file handler
# Use get_logger() or setup_logger() explicitly instead
# default_logger = setup_logger()
