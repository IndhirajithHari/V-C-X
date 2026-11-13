"""Staging index management for VCX."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Optional

from vcx.core.types import IndexEntry


class Index:
    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        self.index_file = self.repo_dir / ".vcx" / "index"
        self._entries: Dict[str, IndexEntry] = {}
        self.load()

    def load(self) -> None:
        """Load index from disk with corruption safety and backups."""
        if not self.index_file.exists():
            self._entries = {}
            return

        try:
            content = self.index_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Index content is not a JSON object")
            self._entries = {
                path: IndexEntry.from_dict(entry) for path, entry in data.items()
            }
        except Exception as err:
            import shutil
            import time

            backup_file = self.index_file.with_name(
                f"index.corrupt.{int(time.time())}"
            )
            try:
                shutil.copy2(self.index_file, backup_file)
            except Exception:
                pass
            raise RuntimeError(
                f"Corrupt index file detected ({err}). Preserved existing index as {backup_file.name}"
            ) from err

    def write(self) -> None:
        """Save index to disk atomically."""
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        data = {path: entry.to_dict() for path, entry in self._entries.items()}
        tmp_file = self.index_file.with_name(f".index_tmp_{self.index_file.name}")
        tmp_file.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_file.replace(self.index_file)

    def add(self, entry: IndexEntry) -> None:
        """Add or update an index entry."""
        self._entries[entry.path] = entry

    def remove(self, path: str) -> None:
        """Remove a path from the index."""
        self._entries.pop(path, None)

    def get(self, path: str) -> Optional[IndexEntry]:
        """Get an entry by relative path."""
        return self._entries.get(path)

    def entries(self) -> List[IndexEntry]:
        """Return list of all index entries sorted by path."""
        return [self._entries[k] for k in sorted(self._entries.keys())]

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def __contains__(self, path: str) -> bool:
        return path in self._entries

    def __len__(self) -> int:
        return len(self._entries)
