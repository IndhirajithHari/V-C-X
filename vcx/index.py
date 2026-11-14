"""SQLite Local Staging & Index for VCX (v2.0).

Replaces text/JSON index with a high-concurrency, ACID-compliant SQLite index
at `.vcx/index.db`. Enables sub-millisecond `status` checks over hundreds of thousands
of files by comparing OS `mtime` and `size` against cached manifests to skip unchanged
files without reading disk bytes.
"""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged'
);

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_mtime_size ON files(mtime, size);
"""


@dataclass
class IndexRow:
    """Represents a tracked file entry in index.db."""
    path: str
    mtime: float
    size: int
    manifest_hash: str
    status: str = "staged"

    @property
    def sha(self) -> str:
        """Alias for manifest_hash for backward compatibility with Git/VCX v1."""
        return self.manifest_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "mtime": self.mtime,
            "size": self.size,
            "manifest_hash": self.manifest_hash,
            "sha": self.manifest_hash,
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IndexRow:
        return cls(
            path=row["path"],
            mtime=float(row["mtime"]),
            size=int(row["size"]),
            manifest_hash=row["manifest_hash"],
            status=row["status"],
        )


class Index:
    """SQLite-backed index managing repository staging and working tree state."""

    def __init__(self, repo_dir: Union[str, Path]):
        self.repo_dir = Path(repo_dir)
        self.db_path = self.repo_dir / ".vcx" / "index.db"
        self.legacy_json_path = self.repo_dir / ".vcx" / "index"
        self._init_db()
        self._migrate_legacy_json_if_needed()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode
        )
        conn.row_factory = sqlite3.Row
        # Optimize SQLite for high-speed metadata reads
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite database tables and indexes."""
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)

    def _migrate_legacy_json_if_needed(self) -> None:
        """Migrate existing .vcx/index JSON data to index.db if present."""
        if not self.legacy_json_path.exists():
            return
        try:
            import json
            content = self.legacy_json_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                with self._get_connection() as conn:
                    for path, entry in data.items():
                        mtime = float(entry.get("mtime", time.time()))
                        size = int(entry.get("size", 0))
                        sha = str(entry.get("sha", entry.get("manifest_hash", "")))
                        status = str(entry.get("status", "staged"))
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO files (path, mtime, size, manifest_hash, status)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (path.replace("\\", "/"), mtime, size, sha, status),
                        )
        except Exception:
            pass  # Legacy migration failure is non-fatal

    def add(
        self,
        path: str,
        mtime: float,
        size: int,
        manifest_hash: str,
        status: str = "staged",
    ) -> None:
        """Add or update an index entry."""
        norm_path = path.replace("\\", "/")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO files (path, mtime, size, manifest_hash, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (norm_path, mtime, size, manifest_hash, status),
            )

    def get(self, path: str) -> Optional[IndexRow]:
        """Fetch index row by relative path."""
        norm_path = path.replace("\\", "/")
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status FROM files WHERE path = ?",
                (norm_path,),
            )
            row = cur.fetchone()
            if row:
                return IndexRow.from_row(row)
        return None

    def remove(self, path: str) -> bool:
        """Remove a path from the index."""
        norm_path = path.replace("\\", "/")
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM files WHERE path = ?", (norm_path,))
            return cur.rowcount > 0

    def clear(self) -> None:
        """Clear all indexed entries."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM files;")

    def entries(self) -> List[IndexRow]:
        """Get all entries sorted by path."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status FROM files ORDER BY path ASC"
            )
            return [IndexRow.from_row(r) for r in cur.fetchall()]

    def staged_entries(self) -> List[IndexRow]:
        """Get all currently staged entries."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status FROM files WHERE status = 'staged' ORDER BY path ASC"
            )
            return [IndexRow.from_row(r) for r in cur.fetchall()]

    def is_file_unchanged(self, path: str, current_mtime: float, current_size: int) -> bool:
        """Check if file matches cached mtime and size in index.db without reading disk bytes."""
        row = self.get(path)
        if not row:
            return False
        # Allow sub-millisecond precision float variance
        return row.size == current_size and abs(row.mtime - current_mtime) < 1e-4

    def update_status(self, path: str, new_status: str) -> None:
        """Update status flag of a file in the index."""
        norm_path = path.replace("\\", "/")
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE files SET status = ? WHERE path = ?",
                (new_status, norm_path),
            )

    def write(self) -> None:
        """No-op for compatibility with legacy json Index.write()."""
        # Data is already persistently committed to SQLite
        pass

    def load(self) -> None:
        """No-op for compatibility with legacy json Index.load()."""
        pass

    def __contains__(self, path: str) -> bool:
        return self.get(path) is not None

    def __len__(self) -> int:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM files")
            return int(cur.fetchone()[0])
