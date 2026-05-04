from __future__ import annotations

import json
import re
from pathlib import Path

from kaos_core.config.settings import KaosSettings

# Allowlist for profile names: alphanumerics, underscore, hyphen, dot.
# Prevents path-traversal (`..`, `/`, `\`) and shell-special characters
# from leaking into the on-disk filename. The reserved suffixes (e.g.
# `.json`) are appended by the manager itself so users never need to.
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")
_RESERVED_PROFILE_NAMES = frozenset(
    {
        "",
        ".",
        "..",
        ".active",  # internal marker file
    }
)


def _validate_profile_name(name: str) -> str:
    """Reject profile names that could escape the profile directory.

    Rejects any name containing a path separator, the special path
    components ``.`` and ``..``, and characters outside the allowlist
    ``[A-Za-z0-9_-.]``. Also rejects the empty string and the
    internal marker name ``.active``.

    Returns ``name`` unchanged when valid; raises ``ValueError`` when
    not. The caller is responsible for surfacing the error to the user.
    """
    if not isinstance(name, str):
        msg = f"Profile name must be a string, got {type(name).__name__}"
        raise ValueError(msg)
    if name in _RESERVED_PROFILE_NAMES:
        msg = f"Profile name '{name}' is reserved"
        raise ValueError(msg)
    if not _PROFILE_NAME_RE.fullmatch(name):
        msg = (
            f"Profile name '{name}' contains disallowed characters; "
            "allowed: letters, digits, underscore, hyphen, dot."
        )
        raise ValueError(msg)
    # Defence in depth: reject anything that could be interpreted as a
    # path component beyond a single filename segment, even if the
    # regex would have allowed it (e.g., long sequences of dots).
    if name.startswith("."):
        # Disallow dotfile-style names so we never accidentally collide
        # with hidden files in the profile directory.
        msg = f"Profile name '{name}' must not start with '.'"
        raise ValueError(msg)
    return name


class ProfileManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(".kaos-profiles")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        """Resolve a profile name to its on-disk JSON path.

        The resulting path is guaranteed to be a direct child of
        ``self.root`` — the validation above prevents path-separator
        and ``..``-style escapes, and the additional ``parent ==
        root`` check catches any remaining edge case (symlinks,
        weird filesystem semantics) before a write or read happens.
        """
        validated = _validate_profile_name(name)
        candidate = (self.root / f"{validated}.json").resolve()
        root_resolved = self.root.resolve()
        if candidate.parent != root_resolved:
            # This should be unreachable given the regex above, but
            # the explicit check makes the invariant audit-friendly.
            msg = f"Profile path {candidate} escapes the profile directory {root_resolved}"
            raise ValueError(msg)
        return candidate

    def load_profile(self, name: str) -> KaosSettings:
        path = self._path(name)
        if not path.exists():
            return KaosSettings(profile_name=name)
        return KaosSettings(profile_name=name, **json.loads(path.read_text()))

    def save_profile(self, name: str, settings: KaosSettings) -> None:
        self._path(name).write_text(
            json.dumps(settings.model_dump(mode="json", exclude={"profile_name"}), indent=2)
        )

    def list_profiles(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json"))

    def get_active_profile(self) -> str:
        marker = self.root / ".active"
        if marker.exists():
            return marker.read_text().strip()
        return "default"

    def set_active_profile(self, name: str) -> None:
        # Validate via the same allowlist used for filenames so the
        # marker file cannot be poisoned with a name that
        # `load_profile()` would later reject.
        validated = _validate_profile_name(name)
        (self.root / ".active").write_text(validated)
