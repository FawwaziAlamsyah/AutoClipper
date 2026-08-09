"""Middleware that logs each request and records its duration."""

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging.logger import get_performance_logger

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log incoming requests to app.log and their duration to performance.log."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Time the request, then log the result and duration."""
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        get_performance_logger().info(
            "%s %s took %.2fms", request.method, request.url.path, duration_ms
        )
        return response
