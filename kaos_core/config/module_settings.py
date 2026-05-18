"""Typed per-module settings base class.

Modules subclass ``ModuleSettings`` to define typed configuration that loads from
environment variables, .env files, and runtime context overrides.
Subclasses that need legacy environment-variable aliases can define a
``legacy_env_vars`` class variable mapping field names to env-var names; those
aliases resolve after canonical ``KAOS_<MOD>_*`` env vars and before ``.env``.

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

import os
from typing import Any, ClassVar, Self

from pydantic_settings import BaseSettings
from pydantic_settings.sources import PydanticBaseSettingsSource


class _LegacyEnvSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        del field
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        legacy_env_vars = getattr(self.settings_cls, "legacy_env_vars", {})
        for field_name, env_names in legacy_env_vars.items():
            if field_name not in self.settings_cls.model_fields:
                continue
            for env_name in env_names:
                value = os.environ.get(env_name)
                if value is not None:
                    values[field_name] = value
                    break
        return values


class ModuleSettings(BaseSettings):
    """Base class for per-module typed settings.

    Values are resolved in priority order:

    1. Explicit ``**overrides`` passed to :meth:`from_context`
    2. ``KaosContext._config`` entries (keyed by field name)
    3. Environment variables (via pydantic-settings, using subclass ``env_prefix``)
    4. Legacy env vars declared in ``legacy_env_vars``
    5. ``.env`` file
    6. Field defaults

    Subclasses must set ``model_config`` with their own ``env_prefix``.
    Legacy env aliases are opt-in per subclass.
    """

    legacy_env_vars: ClassVar[dict[str, tuple[str, ...]]] = {}
    """Legacy env aliases resolved after canonical env vars and before ``.env``."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _LegacyEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @classmethod
    def resolve(cls, settings: Self | None = None) -> Self:
        """Return the provided settings or construct defaults from environment.

        Replaces the common ``_get_settings`` helper pattern found in connectors::

            settings = KaosSourceECFRSettings.resolve(settings)
        """
        return settings if settings is not None else cls()

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
