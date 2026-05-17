"""Typed settings for the artifact subsystem.

These settings control how :class:`ArtifactManifest.to_tool_result` selects
between inlining content, returning a summary plus a resource link, or
returning the resource link alone. They are deliberately first-class
:class:`ModuleSettings` so deployments and per-request overrides can change
the tiering policy without code edits and without resorting to hardcoded
truncation in downstream tools.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from kaos_core.config.module_settings import ModuleSettings


class KaosCoreArtifactSettings(ModuleSettings):
    """Settings for the kaos-core artifact subsystem.

    Env vars use the ``KAOS_CORE_ARTIFACT_`` prefix, e.g.
    ``KAOS_CORE_ARTIFACT_INLINE_THRESHOLD=32768``.
    """

    inline_threshold: int = 16_384
    """Below this size (bytes) it is acceptable to inline the full body."""

    summary_threshold: int = 262_144
    """At or above this size (bytes) only the resource link is returned;
    callers must follow the link to read the body explicitly."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_CORE_ARTIFACT_",
        env_file=".env",
        extra="ignore",
    )
