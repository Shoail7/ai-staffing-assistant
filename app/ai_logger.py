import os
import json
import time
import uuid
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Import request ID context from logging_config to correlate logs
from .logging_config import request_id_ctx

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
CALLS_DIR = LOGS_DIR / "calls"

# Ensure log directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CALLS_DIR.mkdir(parents=True, exist_ok=True)

AI_CALLS_LOG_FILE = LOGS_DIR / "ai_calls.log"
AI_CALLS_JSONL_FILE = LOGS_DIR / "ai_calls.jsonl"

def mask_secrets(data: Any) -> Any:
    """Recursively masks API keys and authorization tokens in URLs, headers, and dicts."""
    if isinstance(data, str):
        # Mask Bearer tokens
        data = re.sub(r'(Bearer\s+)([A-Za-z0-9_\-\.]{6})[A-Za-z0-9_\-\.]+', r'\1\2***', data)
        # Mask query param keys: key=AIzaSy...
        data = re.sub(r'([?&]key=)([A-Za-z0-9_\-\.]{6})[A-Za-z0-9_\-\.]+', r'\1\2***', data)
        return data
    elif isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if k.lower() in ("authorization", "x-api-key", "api-key", "apikey", "key"):
                if isinstance(v, str) and len(v) > 8:
                    masked[k] = v[:6] + "***" + v[-4:]
                else:
                    masked[k] = "***"
            else:
                masked[k] = mask_secrets(v)
        return masked
    elif isinstance(data, list):
        return [mask_secrets(item) for item in data]
    return data

def log_ai_call(
    call_type: str,
    provider: str,
    model: str,
    request_data: Dict[str, Any],
    response_data: Any,
    latency_ms: float,
    status: str = "SUCCESS",
    endpoint: str = "local",
    tokens: Optional[Dict[str, int]] = None,
    cost_usd: float = 0.0,
    error: Optional[str] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Logs comprehensive details of an AI call to:
    1. logs/ai_calls.log (human-readable blocks)
    2. logs/ai_calls.jsonl (line-delimited JSON stream)
    3. logs/calls/{timestamp}_{call_type}_{call_id}.json (individual detailed call file)
    """
    now = datetime.now()
    timestamp_iso = now.isoformat()
    timestamp_file = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
    call_id = str(uuid.uuid4())[:8]
    req_id = request_id or request_id_ctx.get() or "N/A"

    token_info = tokens or {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
    }

    masked_request = mask_secrets(request_data)
    masked_response = mask_secrets(response_data)
    masked_endpoint = mask_secrets(endpoint)

    record = {
        "call_id": call_id,
        "request_id": req_id,
        "timestamp": timestamp_iso,
        "call_type": call_type,
        "provider": provider,
        "model": model,
        "endpoint": masked_endpoint,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "tokens": token_info,
        "cost_usd": round(cost_usd, 6),
        "request": masked_request,
        "response": masked_response,
        "error": error
    }

    try:
        # 1. Write individual JSON file for this specific call
        call_filename = f"{timestamp_file}_{call_type}_{call_id}.json"
        call_file_path = CALLS_DIR / call_filename
        with open(call_file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)

        # 2. Append to JSONL log
        with open(AI_CALLS_JSONL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 3. Append to human-readable log
        log_entry_lines = [
            "=" * 90,
            f"[{timestamp_iso}] [{call_type}] | Call ID: {call_id} | Req ID: {req_id}",
            f"Provider: {provider} | Model: {model} | Status: {status} | Latency: {round(latency_ms, 2)}ms",
            f"Endpoint: {masked_endpoint}",
            f"Tokens: {token_info.get('total_tokens', 0)} (in: {token_info.get('input_tokens', 0)}, out: {token_info.get('output_tokens', 0)}) | Est Cost: ${cost_usd:.6f}",
        ]
        if error:
            log_entry_lines.append(f"ERROR: {error}")
        
        # Add summary of request
        req_preview = json.dumps(masked_request, ensure_ascii=False)
        if len(req_preview) > 300:
            req_preview = req_preview[:300] + "... [truncated]"
        log_entry_lines.append(f"REQUEST PREVIEW: {req_preview}")

        # Add summary of response
        resp_preview = json.dumps(masked_response, ensure_ascii=False)
        if len(resp_preview) > 300:
            resp_preview = resp_preview[:300] + "... [truncated]"
        log_entry_lines.append(f"RESPONSE PREVIEW: {resp_preview}")
        log_entry_lines.append(f"Detailed Record Saved To: logs/calls/{call_filename}")
        log_entry_lines.append("=" * 90 + "\n")

        with open(AI_CALLS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(log_entry_lines) + "\n")

    except Exception as e:
        # Non-blocking fallback if file system write fails
        print(f"[AI LOGGER ERROR] Failed to write AI call log: {e}")

    return record
