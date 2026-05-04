"""Path-traversal hardening tests for ProfileManager.

The previous implementation concatenated the user-supplied profile
name directly into a filesystem path, allowing
``save_profile("../outside", ...)`` to write outside the configured
profile directory. These tests pin the new contract:

- Names matching the allowlist ``[A-Za-z0-9_-.]+`` are accepted.
- Names containing path separators, ``..``, ``.``, leading ``.``, or
  any character outside the allowlist are rejected with ``ValueError``.
- Reserved names (``""``, ``"."``, ``".."``, ``".active"``) are rejected.
- Resolved paths are always direct children of the profile root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core import KaosSettings
from kaos_core.config.profiles import ProfileManager


@pytest.fixture
def manager(tmp_path: Path) -> ProfileManager:
    return ProfileManager(tmp_path / "profiles")


@pytest.mark.parametrize(
    "good_name",
    [
        "default",
        "production",
        "ci-runner",
        "user_42",
        "v1.2.3",
        "a",
        "A1B2",
    ],
)
def test_valid_names_round_trip(manager: ProfileManager, good_name: str) -> None:
    settings = KaosSettings(profile_name=good_name)
    manager.save_profile(good_name, settings)
    assert good_name in manager.list_profiles()
    loaded = manager.load_profile(good_name)
    assert loaded.profile_name == good_name


@pytest.mark.parametrize(
    "bad_name",
    [
        "../outside",
        "../../etc/passwd",
        "subdir/profile",
        "subdir\\profile",
        "/absolute",
        "name with spaces",
        "name;rm -rf /",
        "name$injection",
        "name*glob",
        "name?",
        "name|pipe",
        "name>redirect",
        "name<redirect",
        "name`backtick`",
        "name'quote",
        'name"quote',
        ".hidden",
        "..",
        ".",
        "",
        ".active",
    ],
)
def test_path_traversal_and_special_chars_rejected(manager: ProfileManager, bad_name: str) -> None:
    settings = KaosSettings(profile_name="placeholder")
    with pytest.raises(ValueError):
        manager.save_profile(bad_name, settings)
    with pytest.raises(ValueError):
        manager.load_profile(bad_name)


def test_save_profile_is_confined_to_root(manager: ProfileManager, tmp_path: Path) -> None:
    settings = KaosSettings(profile_name="placeholder")
    with pytest.raises(ValueError):
        manager.save_profile("../escape", settings)
    # Nothing was written outside the profile directory.
    escaped = tmp_path / "escape.json"
    assert not escaped.exists()


def test_set_active_profile_rejects_traversal(manager: ProfileManager) -> None:
    with pytest.raises(ValueError):
        manager.set_active_profile("../poisoned")
    # `.active` marker was not created with a malicious payload.
    marker = manager.root / ".active"
    if marker.exists():
        assert "../" not in marker.read_text()


def test_active_profile_default_is_default(manager: ProfileManager) -> None:
    # No marker -> "default"
    assert manager.get_active_profile() == "default"
    manager.set_active_profile("production")
    assert manager.get_active_profile() == "production"
