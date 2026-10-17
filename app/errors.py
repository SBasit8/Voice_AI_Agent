from typing import Any, Optional


class AppError(Exception):
    """Raised by route handlers to produce the API's standard error envelope
    with a specific HTTP status code, instead of letting FastAPI's default
    (unwrapped) error bodies leak through."""

    def __init__(self, status_code: int, message: str, details: Optional[Any] = None):
        self.status_code = status_code
        self.message = message
        self.details = details
        super().__init__(message)


def envelope(data: Any = None, error: Any = None) -> dict:
    return {"data": data, "error": error}
