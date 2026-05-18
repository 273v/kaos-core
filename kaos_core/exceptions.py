from __future__ import annotations

from typing import Any


class KaosCoreError(Exception):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        return self.message


class RegistryError(KaosCoreError):
    pass


class ToolError(KaosCoreError):
    pass


class ToolExecutionError(ToolError):
    pass


class ResourceError(KaosCoreError):
    pass


class ValidationError(KaosCoreError):
    pass


class ExecutionError(KaosCoreError):
    pass


class WorkflowError(ExecutionError):
    pass


class SamplingError(KaosCoreError):
    pass


class ElicitationError(KaosCoreError):
    pass


class URLElicitationRequiredError(ElicitationError):
    pass


class TaskError(KaosCoreError):
    pass


class UnsafeURLError(KaosCoreError):
    """Raised when a URL fails outbound safety validation.

    Used by ``kaos_core.security.url.validate_outbound_url`` and any caller
    layered on top of it.

    Attributes:
        url: The URL that failed validation.
        reason: Machine-readable cause. One of:
            ``unsafe_scheme``, ``malformed``, ``metadata_service``,
            ``loopback``, ``private_network``, ``disallowed_host``.
        host: Parsed host, or ``None`` if the URL did not parse.
    """

    def __init__(
        self,
        url: str,
        reason: str,
        *,
        host: str | None = None,
        message: str | None = None,
    ) -> None:
        self.url = url
        self.reason = reason
        self.host = host
        details: dict[str, Any] = {"reason": reason}
        if host is not None:
            details["host"] = host
        super().__init__(message or f"URL {url!r} blocked: {reason}", **details)


class ResponseSizeError(KaosCoreError):
    """Raised when an HTTP response exceeds the configured byte cap.

    Used by ``kaos_core.security.size_cap``. The exception fires both for the
    pre-flight ``Content-Length`` check and for the streaming guard.

    Attributes:
        max_bytes: The cap that was exceeded.
        seen_bytes: Bytes accumulated so far (set by the streaming guard).
        content_length: Server-declared ``Content-Length`` header value, if
            present (set by the pre-flight check).
    """

    def __init__(
        self,
        max_bytes: int,
        *,
        seen_bytes: int | None = None,
        content_length: int | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.seen_bytes = seen_bytes
        self.content_length = content_length
        if content_length is not None and seen_bytes is None:
            msg = f"Response Content-Length {content_length} exceeds cap {max_bytes} bytes"
        elif seen_bytes is not None:
            msg = f"Response body grew past cap {max_bytes} bytes (saw {seen_bytes})"
        else:
            msg = f"Response exceeds cap {max_bytes} bytes"
        details: dict[str, Any] = {"max_bytes": max_bytes}
        if seen_bytes is not None:
            details["seen_bytes"] = seen_bytes
        if content_length is not None:
            details["content_length"] = content_length
        super().__init__(msg, **details)
