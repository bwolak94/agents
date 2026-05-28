"""Centralised logging configuration — extracted from api/server.py (#5)."""
import json as _json
import logging
import os


def setup_logging() -> None:
    """Configure root logger from LOG_FORMAT / LOG_LEVEL env vars."""
    log_format = os.getenv("LOG_FORMAT", "text")
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    if log_format == "json":
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info:
                    payload["exc"] = self.formatException(record.exc_info)
                return _json.dumps(payload)

        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.root.handlers = [handler]

    logging.basicConfig(level=level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
