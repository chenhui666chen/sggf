# -*- coding: utf-8 -*-
"""
Logging configuration for model adapter system.
"""

import logging
import sys
from typing import Optional


LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str = "model_adapter") -> logging.Logger:
    """Get or create a logger with the given name."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    
    return logger


def set_log_level(level: int) -> None:
    """Set log level for all model adapter loggers."""
    logging.getLogger("model_adapter").setLevel(level)


def configure_logging(
    level: int = logging.INFO,
    format_str: str = LOG_FORMAT,
    date_format: str = DATE_FORMAT,
    log_file: Optional[str] = None,
) -> None:
    """Configure logging for the model adapter system."""
    root_logger = logging.getLogger("model_adapter")
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    formatter = logging.Formatter(format_str, date_format)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    root_logger.setLevel(level)
    root_logger.propagate = False


logger = get_logger()
