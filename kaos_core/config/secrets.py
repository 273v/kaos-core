"""Secret resolution utilities.

Provides a standard resolution chain for API keys and credentials:
settings (SecretStr) → environment variable → credential store.

The ``credential_store`` argument accepts either the basic
:class:`kaos_core.config.CredentialStore` (plaintext only) or the
tier-aware :class:`kaos_core.config.storage.HardenedCredentialStore`
(F2.1+, walks keyring → encrypted-file → plaintext). Both share the
same ``get(module, service, key)`` shape, so callers swap between
them without changes elsewhere.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic import SecretStr

from kaos_core.config.credentials import CredentialStore

if TYPE_CHECKING:
    from kaos_core.config.storage import HardenedCredentialStore


def resolve_secret(
    settings_value: SecretStr | None = None,
    *,
    env_var: str | None = None,
    credential_store: CredentialStore | HardenedCredentialStore | None = None,
    module: str = "",
    service: str = "",
    key: str = "default",
) -> str | None:
    """Resolve a secret from multiple sources in priority order.

    Resolution order:
    1. ``settings_value`` — a ``SecretStr`` from a ``ModuleSettings`` field
    2. ``env_var`` — an environment variable name (direct ``os.environ`` lookup)
    3. ``credential_store`` — credential store lookup (plaintext or tiered)

    Args:
        settings_value: A pydantic ``SecretStr`` (e.g., from ``KaosWebSettings``).
        env_var: Environment variable name to check as fallback.
        credential_store: A :class:`CredentialStore` (tier-5 plaintext only) or
            :class:`HardenedCredentialStore` (tiered: keyring →
            encrypted-file → plaintext). Both share the ``get`` shape.
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
