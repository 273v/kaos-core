"""Typed per-module settings base class.

Modules subclass ``ModuleSettings`` to define typed configuration that loads from
environment variables, .env files, and runtime context overrides.

Example::

    class KaosWebSettings(ModuleSettings):
        browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
        browser_headless: bool = True

        model_config = SettingsConfigDict(
            env_prefix="KAOS_WEB_", env_file=".env", extra="ignore",
        )

    # From environment only
    settings = KaosWebSettings()

    # With context overrides (highest priority)
    settings = KaosWebSettings.from_context(context, browser_headless=False)
"""

from __future__ import annotations

from typing import Any, Self

from pydantic_settings import BaseSettings


class ModuleSettings(BaseSettings):
    """Base class for per-module typed settings.

    Values are resolved in priority order:

    1. Explicit ``**overrides`` passed to :meth:`from_context`
    2. ``KaosContext._config`` entries (keyed by field name)
    3. Environment variables (via pydantic-settings, using subclass ``env_prefix``)
    4. ``.env`` file
    5. Field defaults

    Subclasses must set ``model_config`` with their own ``env_prefix``.
    """

    @classmethod
    def from_context(
        cls,
        context: Any = None,
        **overrides: Any,
    ) -> Self:
        """Create settings from env vars, overlaid with context config and overrides.

        Args:
            context: A ``KaosContext`` instance. If provided, its ``_config`` dict
                is checked for keys matching this settings class's field names.
            **overrides: Explicit overrides applied last (highest priority).

        Returns:
            A new settings instance with merged values.
        """
        # Start with env + defaults
        base = cls()

        # Collect context overrides for fields that exist in _config
        context_values: dict[str, Any] = {}
        if context is not None:
            config = getattr(context, "_config", None) or {}
            for field_name in cls.model_fields:
                if field_name in config:
                    context_values[field_name] = config[field_name]

        # Merge: context overrides on top of env, explicit overrides on top of context
        merged = {**context_values, **overrides}
        if not merged:
            return base

        # Rebuild with overrides applied
        data = base.model_dump()
        data.update(merged)
        return cls.model_validate(data)
