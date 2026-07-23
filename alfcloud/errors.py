"""alfcloud exceptions."""
from __future__ import annotations


class AlfError(Exception):
    """Base class for all alfcloud errors."""


class AlfAuthError(AlfError):
    """Authentication or token refresh failed (re-auth required)."""


class AlfConnectionError(AlfError):
    """A network transport error (DNS, connection, timeout) - transient, retryable."""


class AlfApiError(AlfError):
    """An API request returned an error status."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
