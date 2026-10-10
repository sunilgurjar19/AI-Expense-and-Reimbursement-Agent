"""Tiny JSON-file persistence. Good enough for a single-process demo."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with self._path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def collection(self, name: str) -> dict[str, Any]:
        return self._data.setdefault(name, {})

    def flush(self) -> None:
        """Atomically write the whole store to disk."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)
            os.replace(tmp, self._path)
