"""Opt-in rotating application logs; credential filtering includes tracebacks."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback
from collections.abc import Mapping

from app.core.paths import safe_path
from .redaction import REDACTED, is_sensitive_key, redact_text


def _safe_log_value(value):
    if isinstance(value, Mapping):
        return {key: REDACTED if is_sensitive_key(str(key)) else _safe_log_value(item)
                for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_safe_log_value(item) for item in value)
    if isinstance(value, list):
        return [_safe_log_value(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Preserve %-placeholders until interpolation; redact the resulting text.
        if not isinstance(record.msg, str):
            record.msg = _safe_log_value(record.msg)
        record.args = _safe_log_value(record.args)
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_text(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)
        for key, value in vars(record).copy().items():
            setattr(record, key, REDACTED if is_sensitive_key(key) else _safe_log_value(value))
        return True


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_logging(path: Path | None = None, *, max_bytes: int = 1024 * 1024,
                      backup_count: int = 3, level: int = logging.INFO,
                      include_app: bool = False) -> logging.Logger:
    if max_bytes <= 0 or backup_count < 1:
        raise ValueError('Cấu hình xoay log không hợp lệ.')
    path = safe_path(path if path is not None else Path('logs/studio.log'))
    # Check existing backup paths too, so rotation cannot follow a planted link.
    for index in range(1, backup_count + 1):
        safe_path(path.with_name(path.name + f'.{index}'))
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count,
                                  encoding='utf-8', delay=True)
    handler.addFilter(RedactingFilter())
    handler._studio_log_handler = True
    handler.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger = logging.getLogger('TikTokYouTubeStudio')
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.addHandler(handler)
    app_logger = logging.getLogger('app')
    for existing in list(app_logger.handlers):
        if getattr(existing, '_studio_log_handler', False):
            app_logger.removeHandler(existing)
    if include_app:
        app_logger.addHandler(handler)
        app_logger.setLevel(level)
    logger.setLevel(level)
    logger.propagate = False
    logger.info('Ứng dụng khởi động; logging đã bật.')
    return logger
