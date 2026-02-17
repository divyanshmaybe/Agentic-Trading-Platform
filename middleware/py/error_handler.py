"""
Error Handler Middleware for FastAPI applications
Provides centralized error handling and formatting
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ErrorHandling(Exception):
    """Custom error class for application errors"""

    def __init__(self, message: str, status_code: int, errors: Optional[list] = None):
        self.message = message
        self.status_code = status_code
        self.errors = errors
        super().__init__(self.message)


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global error handler middleware"""
    error_response: Dict[str, Any] = {
        "error": {
            "status": 500,
            "message": "Internal Server Error",
        }
    }

    # Custom ErrorHandling exception
    if isinstance(exc, ErrorHandling):
        error_response["error"]["status"] = exc.status_code
        error_response["error"]["message"] = exc.message
        if exc.errors:
            error_response["error"]["details"] = exc.errors

    # HTTPException (from FastAPI or Starlette)
    elif isinstance(exc, (HTTPException, StarletteHTTPException)):
        error_response["error"]["status"] = exc.status_code
        error_response["error"]["message"] = exc.detail

    # Pydantic Validation Error
    elif isinstance(exc, RequestValidationError):
        error_response["error"]["status"] = 400
        error_response["error"]["message"] = "Validation Error"
        error_response["error"]["details"] = [
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]

    # Pydantic ValidationError (for schema validation)
    elif isinstance(exc, ValidationError):
        error_response["error"]["status"] = 400
        error_response["error"]["message"] = "Validation Error"
        error_response["error"]["details"] = [
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]

    # MongoDB/Motor duplicate key error
    elif hasattr(exc, "code") and exc.code == 11000:
        error_response["error"]["status"] = 400
        error_response["error"]["message"] = "Duplicate field value"
        error_key = getattr(exc, "details", {}).get("keyValue", {})
        if error_key:
            field = list(error_key.keys())[0]
            error_response["error"]["details"] = f"{field} already exists"

    # JWT Errors
    elif hasattr(exc, "__class__"):
        exc_name = exc.__class__.__name__
        if exc_name == "DecodeError" or exc_name == "InvalidTokenError":
            error_response["error"]["status"] = 401
            error_response["error"]["message"] = "Invalid token"
        elif exc_name == "ExpiredSignatureError":
            error_response["error"]["status"] = 401
            error_response["error"]["message"] = "Token expired"

    # Generic Error
    else:
        error_response["error"]["message"] = str(exc) if exc else "Something went wrong"

    # Include stack trace in development mode
    import os

    if os.getenv("NODE_ENV", "production") == "development":
        import traceback

        error_response["error"]["stack"] = traceback.format_exc()

    logger.error(f"Error handling request: {error_response}")

    return JSONResponse(
        status_code=error_response["error"]["status"],
        content=error_response,
    )

