import logging
import sys
from types import FrameType

from loguru import logger

from app.config.settings import settings


class InterceptHandler(logging.Handler):
    """
    Default handler to redirect standard python logging to loguru.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    # Set log level based on environment
    log_level = "DEBUG" if settings.ENVIRONMENT == "development" else "INFO"

    # Configure loguru logger
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "level": log_level,
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            }
        ]
    )

    # Add InterceptHandler to the root logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(log_level)

    # Intercept loggers for popular frameworks to avoid duplicate/unformatted output
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "sqlalchemy.engine",
    ):
        _logger = logging.getLogger(name)
        _logger.handlers = [InterceptHandler()]
        _logger.propagate = False
        _logger.setLevel(log_level)

    logger.info("Logging successfully initialized with Loguru.")
