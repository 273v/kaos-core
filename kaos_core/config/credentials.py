from __future__ import annotations

import json
from pathlib import Path
from typing import cast


class CredentialStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(".kaos-credentials.json")

    def _load(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.path.exists():
            return {}
        return cast(dict[str, dict[str, dict[str, str]]], json.loads(self.path.read_text()))

    def _save(self, data: dict[str, dict[str, dict[str, str]]]) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        return self._load().get(module, {}).get(service, {}).get(key)

    def set(self, module: str, service: str, key: str, value: str) -> None:
        data = self._load()
        data.setdefault(module, {}).setdefault(service, {})[key] = value
        self._save(data)

    def delete(self, module: str, service: str, key: str = "default") -> None:
        data = self._load()
        service_data = data.get(module, {}).get(service, {})
        service_data.pop(key, None)
        self._save(data)

    def list_services(self, module: str) -> list[str]:
        return sorted(self._load().get(module, {}).keys())
