from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlparse, urlunparse


DEFAULT_LOG_PATH = Path("logs") / "riskua_diagnostic.log"
DEFAULT_MAX_LINES = 2000
LOGGER_NAME = "riskua.diagnostic"
SECRET_QUERY_KEYS = {
    "token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "password",
    "pass",
    "access_token",
    "bot_token",
}


class LineCappedFileHandler(logging.Handler):
    def __init__(self, log_path: str | os.PathLike[str], *, max_lines: int = DEFAULT_MAX_LINES) -> None:
        super().__init__(level=logging.INFO)
        self.log_path = Path(log_path)
        self.max_lines = max(1, int(max_lines))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._line_count = self._count_existing_lines()

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        if self._line_count >= self.max_lines:
            mode = "w"
            self._line_count = 0
        else:
            mode = "a"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open(mode, encoding="utf-8") as log_file:
            log_file.write(message + "\n")
        self._line_count += 1

    def _count_existing_lines(self) -> int:
        if not self.log_path.exists():
            return 0
        try:
            with self.log_path.open("r", encoding="utf-8") as log_file:
                return sum(1 for _line in log_file)
        except OSError:
            return 0


def configure_diagnostic_logging(
    *,
    log_path: str | os.PathLike[str] | None = None,
    max_lines: int | None = None,
) -> Path:
    resolved_path = Path(log_path or os.environ.get("RISKUA_DIAGNOSTIC_LOG") or DEFAULT_LOG_PATH)
    resolved_max_lines = max_lines or int(os.environ.get("RISKUA_DIAGNOSTIC_LOG_MAX_LINES", DEFAULT_MAX_LINES))
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if isinstance(handler, LineCappedFileHandler):
            logger.removeHandler(handler)
            handler.close()
    handler = LineCappedFileHandler(resolved_path, max_lines=resolved_max_lines)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    resolved_path.touch(exist_ok=True)
    return resolved_path


def log_diagnostic_event(event: str, **fields: Any) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler, LineCappedFileHandler) for handler in logger.handlers):
        configure_diagnostic_logging()
    payload = sanitize_payload({"event": event, **fields})
    try:
        logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except OSError:
        logging.getLogger(__name__).debug("Diagnostic log write failed", exc_info=True)


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: sanitize_value(key, value) for key, value in payload.items()}


def sanitize_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        if lowered_key in {"url", "raw_url", "final_url", "request_url"}:
            return sanitize_url(value)
        if lowered_key in {"response", "response_text", "response_preview", "html"}:
            return preview(value)
        if lowered_key in SECRET_QUERY_KEYS:
            return "<redacted>"
        return preview(value, limit=1000)
    if isinstance(value, dict):
        return sanitize_payload(value)
    if isinstance(value, (list, tuple)):
        return [sanitize_value(key, item) for item in value[:20]]
    return preview(str(value))


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        safe_key = quote_plus(key)
        safe_value = "<redacted>" if key.lower() in SECRET_QUERY_KEYS else quote_plus(value)
        query.append(f"{safe_key}={safe_value}")
    return urlunparse(parsed._replace(query="&".join(query)))


def preview(value: str, *, limit: int = 500) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}..."
