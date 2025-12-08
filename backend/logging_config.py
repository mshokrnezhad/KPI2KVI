import logging
import logging.config
from pathlib import Path
from typing import Dict


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Directory for session-specific logs
SESSION_LOG_DIR = LOG_DIR / "sessions"
SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Cache of session loggers to avoid recreating them
_session_loggers: Dict[str, logging.Logger] = {}


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure app-wide logging with rotation to file and console."""

    logging_config = {
        "version": 1,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            },
            "uvicorn.access": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(client_addr)s - %(request_line)s %(status_code)s",  # noqa: E501
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": str(LOG_DIR / "app.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
            },
        },
        "loggers": {
            "uvicorn.error": {"level": level, "handlers": ["console", "file"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["console", "file"], "propagate": False},
        },
        "root": {
            "level": level,
            "handlers": ["console", "file"],
        },
    }

    logging.config.dictConfig(logging_config)
    return logging.getLogger("backend")


def get_session_logger(session_id: str, level: str = "INFO") -> logging.Logger:
    """
    Get or create a logger specific to a session.
    Each session gets its own log file in logs/sessions/
    
    Args:
        session_id: Unique session identifier
        level: Logging level (default: INFO)
        
    Returns:
        Logger instance for the session
    """
    # Return cached logger if it exists
    if session_id in _session_loggers:
        return _session_loggers[session_id]
    
    # Create new logger for this session
    logger_name = f"session.{session_id}"
    session_logger = logging.getLogger(logger_name)
    session_logger.setLevel(level)
    
    # Prevent propagation to root logger to avoid duplicate logs
    session_logger.propagate = False
    
    # Create file handler for this session
    log_file = SESSION_LOG_DIR / f"{session_id}.log"
    file_handler = logging.FileHandler(str(log_file), mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    
    # Add handler to logger
    session_logger.addHandler(file_handler)
    
    # Also add console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    session_logger.addHandler(console_handler)
    
    # Cache the logger
    _session_loggers[session_id] = session_logger
    
    session_logger.info(f"=== Session {session_id} started ===")
    
    return session_logger


def close_session_logger(session_id: str) -> None:
    """
    Close and remove a session logger.
    Should be called when a session is pruned or explicitly ended.
    
    Args:
        session_id: Session identifier
    """
    if session_id in _session_loggers:
        logger = _session_loggers[session_id]
        logger.info(f"=== Session {session_id} ended ===")
        
        # Close all handlers
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        
        # Remove from cache
        del _session_loggers[session_id]
