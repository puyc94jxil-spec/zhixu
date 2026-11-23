"""日志只记录事件、错误码和标识。

禁止把密码、Cookie、密钥、文档正文、提示词或引用原文写入日志。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_LOGGER_NAME = "zhixu"
_FORBIDDEN = {
    "password",
    "authorization",
    "cookie",
    "api_key",
    "model_api_key",
    "text",
    "content",
    "quote",
    "prompt",
    "messages",
    "secret",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                if key.lower() in _FORBIDDEN:
                    continue
                if isinstance(value, str) and len(value) > 200:
                    continue
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def get_logger(log_path: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        stream = logging.StreamHandler()
        stream.setFormatter(_JsonFormatter())
        logger.addHandler(stream)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
                handler.close()
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(_JsonFormatter())
        logger.addHandler(file_handler)
    return logger


def log_event(event: str, **fields: object) -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        get_logger()
    logger.info(event, extra={"fields": fields})
