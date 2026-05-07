from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRETS_DIR = Path("/run/secrets")


class KaosSettings(BaseSettings):
    log_level: str = "INFO"
    log_file: Path | None = None
    log_format: str = "text"
    cache_enabled: bool = True
    cache_directory: Path = Path(".kaos-cache")
    timeout: float = 30.0
    retry_limit: int = 2
    max_concurrent_requests: int = 8
    task_management_enabled: bool = False
    artifact_manifest_context_id: str = "__kaos_artifacts__"
    artifact_manifest_prefix: str = "manifests"
    artifact_inline_read_max_bytes: int = Field(default=262_144, ge=1)
    artifact_chunk_size_bytes: int = Field(default=65_536, ge=1)
    artifact_temporary_ttl_seconds: int = Field(default=3_600, ge=1)
    credential_store_path: Path = Field(default=Path(".kaos-credentials.json"), exclude=True)
    profile_name: str = Field(default="default", exclude=True)

    model_config = SettingsConfigDict(
        env_prefix="KAOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir=str(DEFAULT_SECRETS_DIR) if DEFAULT_SECRETS_DIR.exists() else None,
        extra="ignore",
    )
