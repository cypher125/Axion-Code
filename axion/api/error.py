"""API error types.

Maps to: rust/crates/api/src/error.rs
"""

from __future__ import annotations

CONTEXT_WINDOW_ERROR_MARKERS = [
    "maximum context length",
    "context window",
    "context length",
    "too many tokens",
    "prompt is too long",
    "input is too long",
    "request is too large",
]

GENERIC_FATAL_WRAPPER_MARKERS = [
    "something went wrong while processing your request",
    "please try again, or use /new to start a fresh session",
]


class ApiError(Exception):
    """Base class for all API errors."""

    def is_retryable(self) -> bool:
        return False

    def request_id(self) -> str | None:
        return None


class MissingCredentialsError(ApiError):
    """No API key or OAuth token available."""

    def __init__(self, provider: str, env_vars: list[str]) -> None:
        self.provider = provider
        self.env_vars = env_vars
        super().__init__(
            f"Missing credentials for {provider}. "
            f"Set one of: {', '.join(env_vars)}"
        )


class ContextWindowExceededError(ApiError):
    """Request exceeds the model's context window."""

    def __init__(
        self,
        model: str,
        estimated_input_tokens: int,
        requested_output_tokens: int,
        estimated_total_tokens: int,
        context_window_tokens: int,
    ) -> None:
        self.model = model
        self.estimated_input_tokens = estimated_input_tokens
        self.requested_output_tokens = requested_output_tokens
        self.estimated_total_tokens = estimated_total_tokens
        self.context_window_tokens = context_window_tokens
        super().__init__(
            f"Context window exceeded for {model}: "
            f"{estimated_total_tokens} tokens > {context_window_tokens} limit"
        )


class ExpiredOAuthTokenError(ApiError):
    """OAuth token has expired."""

    def __init__(self) -> None:
        super().__init__("OAuth token has expired")


class AuthError(ApiError):
    """Authentication failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class HttpError(ApiError):
    """Low-level HTTP transport error."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)

    def is_retryable(self) -> bool:
        return True


class ApiResponseError(ApiError):
    """API returned an error response."""

    def __init__(
        self,
        status: int,
        error_type: str | None = None,
        message: str | None = None,
        request_id_val: str | None = None,
        body: str = "",
        retryable: bool = False,
    ) -> None:
        self.status = status
        self.error_type = error_type
        self._message = message
        self._request_id = request_id_val
        self.body = body
        self.retryable = retryable
        detail = message or body[:200]
        super().__init__(f"API error {status}: {detail}")

    def is_retryable(self) -> bool:
        return self.retryable

    def request_id(self) -> str | None:
        return self._request_id


class RetriesExhaustedError(ApiError):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: ApiError) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Exhausted {attempts} retries. Last error: {last_error}")

    def is_retryable(self) -> bool:
        return self.last_error.is_retryable()

    def request_id(self) -> str | None:
        return self.last_error.request_id()


class InvalidSseFrameError(ApiError):
    """SSE frame could not be parsed."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid SSE frame: {reason}")


class BackoffOverflowError(ApiError):
    """Backoff delay calculation overflowed."""

    def __init__(self, attempt: int, base_delay_ms: int) -> None:
        self.attempt = attempt
        self.base_delay_ms = base_delay_ms
        super().__init__(f"Backoff overflow at attempt {attempt}")


def looks_like_context_window_error(message: str) -> bool:
    """Check if an error message indicates a context window exceeded error."""
    lower = message.lower()
    return any(marker in lower for marker in CONTEXT_WINDOW_ERROR_MARKERS)


def looks_like_generic_fatal_error(message: str) -> bool:
    """Check if an error message indicates a generic fatal wrapper error."""
    lower = message.lower()
    return any(marker in lower for marker in GENERIC_FATAL_WRAPPER_MARKERS)
