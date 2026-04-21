"""Structured JSON logging for APE experiments."""
import logging
import os
import sys
import time

from pythonjsonlogger import jsonlogger
from termcolor import colored


def create_logger(output_dir="outputs/logger", name="", log_level=logging.INFO, log_file=None, show_details=False):
    """Create a structured JSON logger that writes to both file and console.

    Args:
        output_dir: Directory to store log files.
        name: Logger name and suffix of the auto-generated filename.
        log_level: Logging level for the console handler.
        log_file: Explicit path for the log file; auto-generated if None.
        show_details: Whether to show detailed information in the console output.

    Returns:
        Tuple of (logger, log_file_path).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Avoid adding duplicate handlers when the same logger is retrieved again
    if logger.handlers:
        log_file = log_file or next(
            (h.baseFilename for h in logger.handlers if isinstance(h, logging.FileHandler)), ""
        )
        return logger, log_file

    os.makedirs(output_dir, exist_ok=True)
    start_time = time.strftime("%y-%m-%d-%H%M", time.localtime())

    json_fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(message)s",
        rename_fields={"levelname": "level", "asctime": "time"},
    )
    if show_details:
        console_fmt = (
            colored("[%(asctime)s]", "green") + ": %(levelname)s" + colored(" %(message)s", "blue")
        )
    else:
        console_fmt = colored(" %(message)s ...", "blue")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(fmt=console_fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = os.path.join(output_dir, f"{start_time}_{name}.log")
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(json_fmt)
    logger.addHandler(file_handler)

    return logger, log_file
