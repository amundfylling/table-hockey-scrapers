"""galdahokejs.lv (to 2025-11) and escore.live (from 2025-12) cover the same Latvian players. Before one of
them gives a player a new source-local id, it looks the name up in the other's registry and reuses that id
when exactly one id carries the name there, so a player without an ITHF or Sportscorpion id keeps one id."""

from __future__ import annotations

from pathlib import Path

from .players import name_key
from .registry import IdRegistry


class OtherRegistry:
    def __init__(self, path: Path):
        reg = IdRegistry(path, 1, ("name",))
        self.by_name = reg.ids_by_name(name_key)

    def unique_id(self, name: str) -> int | None:
        ids = self.by_name.get(name_key(name), set())
        return next(iter(ids)) if len(ids) == 1 else None
