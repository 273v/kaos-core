"""Secret resolution utilities.

Provides a standard resolution chain for API keys and credentials:
settings (SecretStr) → environment variable → credential store.
"""

from __future__ import annotations

import os

from pydantic import SecretStr

from kaos_core.config.credentials import CredentialStore


def resolve_secret(
    settings_value: SecretStr | None = None,
    *,
    env_var: str | None = None,
    credential_store: CredentialStore | None = None,
    module: str = "",
    service: str = "",
    key: str = "default",
) -> str | None:
    """Resolve a secret from multiple sources in priority order.

    Resolution order:
    1. ``settings_value`` — a ``SecretStr`` from a ``ModuleSettings`` field
    2. ``env_var`` — an environment variable name (direct ``os.environ`` lookup)
    3. ``credential_store`` — file-based credential store lookup

    Args:
        settings_value: A pydantic ``SecretStr`` (e.g., from ``KaosWebSettings``).
        env_var: Environment variable name to check as fallback.
        credential_store: A ``CredentialStore`` instance for file-based lookup.
        module: Module name for credential store (e.g., ``"web"``).
        service: Service name for credential store (e.g., ``"serpapi"``).
        key: Key within the credential store service (default: ``"default"``).

    Returns:
        The resolved secret string, or ``None`` if not found in any source.
    """
    # 1. Settings (pydantic SecretStr from env via pydantic-settings)
    if settings_value is not None:
        return settings_value.get_secret_value()

    # 2. Direct env var fallback
    if env_var is not None:
        value = os.environ.get(env_var)
        if value:
            return value

    # 3. Credential store
    if credential_store is not None and module and service:
        return credential_store.get(module, service, key)

    return None
