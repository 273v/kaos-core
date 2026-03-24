from __future__ import annotations

from kaos_core.types.content import KaosModel


class Root(KaosModel):
    uri: str
    name: str | None = None


class RootsListChangedNotification(KaosModel):
    method: str = "notifications/roots/list_changed"


class ListRootsResult(KaosModel):
    roots: list[Root]
