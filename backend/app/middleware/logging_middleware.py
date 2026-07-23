import time
from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log request execution times, endpoints, and response status.
    Useful for performance tracing and analytics.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Ensure exceptions are logged with context
            process_time = (time.time() - start_time) * 1000
            logger.error(
                f"Request failed: {request.method} {request.url.path} - "
                f"Duration: {process_time:.2f}ms - Exception: {str(exc)}"
            )
            raise exc

        process_time = (time.time() - start_time) * 1000
        logger.info(
            f"HTTP {request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Duration: {process_time:.2f}ms"
        )
        return response
