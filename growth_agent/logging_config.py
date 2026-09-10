import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key in ("run_id", "request_id", "status_code", "duration_ms", "stage", "error_type"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        # Never serialize payloads, URLs, credentials, exception text or model content.
        return json.dumps(result, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger("growth_agent")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
