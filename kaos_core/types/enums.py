from __future__ import annotations

from enum import StrEnum


class ToolCapability(StrEnum):
    EXTRACT = "extract"
    ANALYZE = "analyze"
    TRANSFORM = "transform"
    QUERY = "query"
    GENERATE = "generate"
    VALIDATE = "validate"


class ToolCategory(StrEnum):
    DOCUMENT = "document"
    TEXT = "text"
    DATA = "data"
    MEDIA = "media"
    INTEGRATION = "integration"
    UTILITY = "utility"
    AGENT = "agent"


class ResourceType(StrEnum):
    DOCUMENT = "document"
    DATASET = "dataset"
    MODEL = "model"
    CONFIGURATION = "configuration"
    TEMPLATE = "template"
    PAGE = "page"
    EXTRACTION = "extraction"


class ExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskState(StrEnum):
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ElicitationMode(StrEnum):
    FORM = "form"
    URL = "url"


class StorageBackend(StrEnum):
    MEMORY = "memory"
    DISK = "disk"
    S3 = "s3"
    HYBRID = "hybrid"


class IsolationMode(StrEnum):
    GLOBAL = "global"
    NAMESPACE = "namespace"
    CONTEXT = "context"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
