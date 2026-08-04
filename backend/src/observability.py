"""Safe, file-based diagnostics for failed backend API calls."""

import hashlib
import json
import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request


_DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_REQUEST_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar("api_error_request_context", default=None)
_ACTIVE_ERROR_LOGGER: ContextVar[logging.Logger | None] = ContextVar("active_api_error_logger", default=None)


def _error_logger(log_dir: Path | None = None) -> logging.Logger:
    """Return a dedicated rotating logger for structured API error records."""
    destination = (log_dir or Path(os.getenv("API_ERROR_LOG_DIR", _DEFAULT_LOG_DIR))).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    log_path = destination / "api-errors.jsonl"
    logger_name = f"vsf.backend.api_errors.{hashlib.sha256(str(log_path).encode()).hexdigest()[:12]}"
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        logger.propagate = False

    return logger


def install_api_error_logging(app: FastAPI, log_dir: Path | None = None) -> None:
    """Log server-side API failures without persisting request payloads or headers.

    The log destination defaults to ``backend/logs/api-errors.jsonl`` and can be
    changed with ``API_ERROR_LOG_DIR``. Each line is an independent JSON record.
    """
    logger = _error_logger(log_dir)

    @app.middleware("http")
    async def log_api_error(request: Request, call_next):
        request_id = uuid4().hex
        started_at = perf_counter()
        context_token = _REQUEST_CONTEXT.set(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            }
        )
        logger_token = _ACTIVE_ERROR_LOGGER.set(logger)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                _write_api_error(
                    logger=logger,
                    request_id=request_id,
                    request=request,
                    status_code=500,
                    duration_ms=(perf_counter() - started_at) * 1000,
                    exception_type=type(exc).__name__,
                )
                raise

            response.headers["X-Request-ID"] = request_id
            if response.status_code >= 500:
                _write_api_error(
                    logger=logger,
                    request_id=request_id,
                    request=request,
                    status_code=response.status_code,
                    duration_ms=(perf_counter() - started_at) * 1000,
                )
            return response
        finally:
            _ACTIVE_ERROR_LOGGER.reset(logger_token)
            _REQUEST_CONTEXT.reset(context_token)


def _write_api_error(
    *,
    logger: logging.Logger,
    request_id: str,
    request: Request,
    status_code: int,
    duration_ms: float,
    exception_type: str | None = None,
) -> None:
    """Write the minimum useful, non-sensitive context for one failed API call."""
    record = {
        "event": "api_error",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
    }
    if exception_type:
        record["exception_type"] = exception_type
    logger.error(json.dumps(record, ensure_ascii=False, separators=(",", ":")))


def log_sanitized_system_error(*, session_id: str | None, raw_text: str) -> None:
    """Record a sanitized agent error without persisting its potentially sensitive text."""
    record: dict[str, str | int] = {
        "event": "sanitized_system_error",
        "error_fingerprint": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "error_length": len(raw_text),
    }
    if session_id:
        record["session_id"] = session_id
    if request_context := _REQUEST_CONTEXT.get():
        record.update(request_context)

    logger = _ACTIVE_ERROR_LOGGER.get() or _error_logger()
    logger.error(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
