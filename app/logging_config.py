import logging
import time
import uuid
import json
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Request ID Context Variable for async tracing
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        req_id = request_id_ctx.get() or getattr(record, "request_id", "NO_REQ")
        data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "request_id": req_id,
            "module": record.module,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            data.update(record.extra_data)
        return json.dumps(data)

def setup_logger(name: str = "ai_staffing") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [req:%(request_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

class RequestTracker:
    """Tracks latency and logs steps for an individual chat request."""
    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]
        self.token = request_id_ctx.set(self.request_id)
        self.start_time = time.perf_counter()
        self.step_latencies: Dict[str, float] = {}
        self.logger = logging.getLogger("ai_staffing")

    def record_step(self, step_name: str, duration_sec: float, details: Optional[Dict[str, Any]] = None):
        ms = round(duration_sec * 1000, 2)
        self.step_latencies[step_name] = ms
        detail_str = f" | {json.dumps(details)}" if details else ""
        self.logger.info(
            f"Step [{step_name}] completed in {ms}ms{detail_str}",
            extra={"request_id": self.request_id}
        )

    def total_elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.start_time) * 1000, 2)

    def close(self):
        request_id_ctx.reset(self.token)
