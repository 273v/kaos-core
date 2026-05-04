from __future__ import annotations

from typing import Any


class KaosCoreError(Exception):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if not self.details:
            return self.message
        return f"{self.message} ({self.details})"


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
