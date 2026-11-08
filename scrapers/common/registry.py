"""Persistent, committed id registries: a key gets a number once and keeps it forever."""

from __future__ import annotations

import csv
from pathlib import Path


class IdRegistry:
    """CSV-backed ``key -> id`` map.

    New keys get ``max(existing ids, first - 1) + 1``. Ids are never reused or renumbered, even if a key
    disappears from the source. Extra columns (e.g. a display name) are stored for human review only.
    """

    def __init__(self, path: Path, first: int, extra_fields: tuple[str, ...] = ()):
        self.path = Path(path)
        self.first = first
        self.extra_fields = tuple(extra_fields)
        self._ids: dict[str, int] = {}
        self._extra: dict[str, dict[str, str]] = {}
        self._dirty = False
        if self.path.exists():
            with self.path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    self._ids[row["key"]] = int(row["id"])
                    self._extra[row["key"]] = {f: row.get(f, "") or "" for f in self.extra_fields}

    def __contains__(self, key: str) -> bool:
        return key in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def lookup(self, key: str) -> int | None:
        return self._ids.get(key)

    def get(self, key: str, **extra: str) -> int:
        key = str(key)
        if key not in self._ids:
            nxt = max(self._ids.values(), default=self.first - 1) + 1
            self._ids[key] = max(nxt, self.first)
            self._extra[key] = {f: str(extra.get(f, "")) for f in self.extra_fields}
            self._dirty = True
        return self._ids[key]

    def assign(self, key: str, value: int, **extra: str) -> int:
        """Store a given id for a new key (e.g. one reused from another source's registry)."""
        key = str(key)
        if key not in self._ids:
            self._ids[key] = int(value)
            self._extra[key] = {f: str(extra.get(f, "")) for f in self.extra_fields}
            self._dirty = True
        return self._ids[key]

    def ids_by_name(self, key_func) -> dict:
        """``key_func(name column) -> set of ids``, for looking a player up by name in another registry."""
        out: dict = {}
        for key, value in self._ids.items():
            name = self._extra.get(key, {}).get("name", "")
            if name:
                out.setdefault(key_func(name), set()).add(value)
        return out

    def save(self) -> None:
        if not self._dirty and self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["key", "id", *self.extra_fields])
            for key, value in sorted(self._ids.items(), key=lambda kv: kv[1]):
                writer.writerow([key, value, *(self._extra.get(key, {}).get(f, "") for f in self.extra_fields)])
        tmp.replace(self.path)
        self._dirty = False
