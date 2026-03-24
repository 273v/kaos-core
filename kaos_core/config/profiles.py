from __future__ import annotations

import json
from pathlib import Path

from kaos_core.config.settings import KaosSettings


class ProfileManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(".kaos-profiles")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

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
        (self.root / ".active").write_text(name)
