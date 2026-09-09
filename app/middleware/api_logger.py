"""
API Request / Response Logger Middleware
----------------------------------------
Logs every HTTP request and response to the `api_logs` DB table.

ENABLE:  API_LOGGING_ENABLED=true  in .env  (default: true for dev)
DISABLE: API_LOGGING_ENABLED=false in .env  (set this in production after green flags)

Usage in main.py:
    from app.middleware.api_logger import ApiLoggerMiddleware
    app.add_middleware(ApiLoggerMiddleware)
"""

import os
import json
import time
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import SessionLocal

logger = logging.getLogger("api_logger")

# Toggle via .env — disable once deployment is stable
API_LOGGING_ENABLED = os.getenv("API_LOGGING_ENABLED", "true").lower() == "true"

# Endpoints to skip (health checks, SSE streams, static files)
SKIP_ENDPOINTS = {"/", "/docs", "/openapi.json", "/redoc", "/metrics"}
SKIP_PREFIXES  = ("/telemetry/live", "/sse", "/ws", "/_next", "/static")

# Mask sensitive fields in request body
SENSITIVE_FIELDS = {"password", "confirm_password", "new_password",
                    "current_password", "confirm_new_password", "refresh_token"}


def _mask_sensitive(data: dict) -> dict:
    """Replace sensitive field values with '***'."""
    if not isinstance(data, dict):
        return data
    return {
        k: "***" if k.lower() in SENSITIVE_FIELDS else v
        for k, v in data.items()
    }


def _extract_employee_id(request: Request) -> Optional[str]:
    """Try to decode employee_id from JWT without raising errors."""
    try:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
        from jose import jwt as jose_jwt
        from app.database import settings
        payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


class ApiLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip if logging is disabled globally
        if not API_LOGGING_ENABLED:
            return await call_next(request)

        path = request.url.path

        # Skip health / SSE / websocket / static endpoints
        if path in SKIP_ENDPOINTS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        start_time   = time.time()
        request_body = None
        error_detail = None

        # Read request body (only for non-GET)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                raw = await request.body()
                body_json = json.loads(raw.decode("utf-8"))
                request_body = json.dumps(_mask_sensitive(body_json))
            except Exception:
                request_body = None

        # Call the actual endpoint
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            error_detail = str(exc)
            raise
        finally:
            elapsed_ms = int((time.time() - start_time) * 1000)

        # Read response body (clone it — it's a stream)
        response_body_text = None
        try:
            resp_body_bytes = b""
            async for chunk in response.body_iterator:
                resp_body_bytes += chunk

            response_body_text = resp_body_bytes.decode("utf-8")[:2000]  # truncate at 2000 chars

            # Rebuild the response since we consumed the body iterator
            from starlette.responses import Response as StarletteResponse
            response = StarletteResponse(
                content=resp_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception:
            pass

        # Get client IP
        ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")

        # Save to DB asynchronously (non-blocking fire-and-forget)
        try:
            from app.models.models import ApiLog
            db = SessionLocal()
            try:
                log_entry = ApiLog(
                    method           = request.method,
                    endpoint         = path,
                    query_params     = str(request.query_params) or None,
                    request_body     = request_body,
                    response_body    = response_body_text,
                    status_code      = response.status_code,
                    employee_id      = _extract_employee_id(request),
                    ip_address       = ip.split(",")[0].strip(),
                    response_time_ms = elapsed_ms,
                    error_detail     = error_detail,
                )
                db.add(log_entry)
                db.commit()
            except Exception as db_err:
                logger.warning(f"ApiLogger DB write failed: {db_err}")
                db.rollback()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"ApiLogger error: {e}")

        return response
