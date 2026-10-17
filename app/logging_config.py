import json
import logging
import sys
from datetime import datetime, timezone

from .config import settings

_RESERVED = logging.LogRecord(None, None, "", 0, "", (), None).__dict__.keys()


class JsonFormatter(logging.Formatter):
    """Structured JSON-lines logging to stdout.

    Render (and most PaaS hosts) capture stdout directly, so this satisfies
    the assessment's observability requirement ("log agent conversations /
    the final collected data payload to stdout or a log file") without any
    extra infrastructure, while staying greppable/parseable.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)

    # Keep uvicorn's access/error logs flowing through the same handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
