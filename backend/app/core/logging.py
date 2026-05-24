import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Optional

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("user_id", default=None)
session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("session_id", default=None)


_STANDARD_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "session_id": session_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_root_logger() -> None:
    root_logger = logging.getLogger()
    if any(getattr(handler, "_breach_replay_json", False) for handler in root_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler._breach_replay_json = True
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def set_request_context(request_id: Optional[str], user_id: Optional[str], session_id: Optional[str]) -> None:
    request_id_var.set(request_id)
    user_id_var.set(user_id)
    session_id_var.set(session_id)


def set_user_context(user_id: str) -> None:
    user_id_var.set(user_id)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure JSON structured logging for the application."""
    _configure_root_logger()
    logging.getLogger().setLevel(level)


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)
