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
import shutil
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

DEFAULT_FILE_MODE = 0o644  # 420 decimal

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged',
    mode INTEGER NOT NULL DEFAULT 420
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
    mode: int = DEFAULT_FILE_MODE

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
            "mode": self.mode,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IndexRow:
        mode_val = DEFAULT_FILE_MODE
        try:
            if "mode" in row.keys() and row["mode"] is not None:
                mode_val = int(row["mode"])
        except Exception:
            pass
        return cls(
            path=row["path"],
            mtime=float(row["mtime"]),
            size=int(row["size"]),
            manifest_hash=row["manifest_hash"],
            status=row["status"],
            mode=mode_val,
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
        # Set busy handler timeout immediately (30,000ms = 30s)
        conn.execute("PRAGMA busy_timeout = 30000;")
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA temp_store = MEMORY;")
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass
        return conn

    def _execute_with_retry(
        self, fn: Callable[[sqlite3.Connection], Any], max_retries: int = 5, initial_backoff: float = 0.05
    ) -> Any:
        """Execute a database function with exponential backoff on lock contention."""
        backoff = initial_backoff
        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn:
                    return fn(conn)
            except sqlite3.OperationalError as e:
                err_msg = str(e).lower()
                if ("locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        """Initialize SQLite database tables and indexes with corrupt DB safety."""
        def _op(conn: sqlite3.Connection):
            # Verify database integrity before executing schema
            cur = conn.execute("PRAGMA quick_check(1);")
            row = cur.fetchone()
            if row and row[0] != "ok":
                raise sqlite3.DatabaseError(f"Database corruption: {row[0]}")
            conn.executescript(SCHEMA)
            # Ensure mode column exists for existing databases
            cur = conn.execute("PRAGMA table_info(files);")
            cols = [r["name"] for r in cur.fetchall()]
            if "mode" not in cols:
                conn.execute(f"ALTER TABLE files ADD COLUMN mode INTEGER DEFAULT {DEFAULT_FILE_MODE};")

        try:
            self._execute_with_retry(_op)
        except sqlite3.DatabaseError as e:
            # Corrupt database detected - backup and recreate
            backup_path = self.db_path.with_name(f"index.db.corrupt.{int(time.time())}_{os.urandom(2).hex()}")
            try:
                if self.db_path.exists():
                    shutil.copy2(self.db_path, backup_path)
                    self.db_path.unlink(missing_ok=True)
                for f in self.db_path.parent.glob(f"{self.db_path.name}*"):
                    if "-wal" in f.name or "-shm" in f.name:
                        f.unlink(missing_ok=True)
                self._execute_with_retry(_op)
            except Exception:
                raise RuntimeError(f"Corrupt index database detected ({e}) and failed to recover") from e

    def _migrate_legacy_json_if_needed(self) -> None:
        """Migrate existing .vcx/index JSON data to index.db if present."""
        if not self.legacy_json_path.exists():
            return
        try:
            import json
            content = self.legacy_json_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                def _op(conn: sqlite3.Connection):
                    for path, entry in data.items():
                        mtime = float(entry.get("mtime", time.time()))
                        size = int(entry.get("size", 0))
                        sha = str(entry.get("sha", entry.get("manifest_hash", "")))
                        status = str(entry.get("status", "staged"))
                        raw_mode = entry.get("mode", DEFAULT_FILE_MODE)
                        if isinstance(raw_mode, str) and ("755" in raw_mode or raw_mode == "100755"):
                            mode = 0o755
                        elif isinstance(raw_mode, int):
                            mode = raw_mode
                        else:
                            mode = DEFAULT_FILE_MODE
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO files (path, mtime, size, manifest_hash, status, mode)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (path.replace("\\", "/"), mtime, size, sha, status, mode),
                        )
                self._execute_with_retry(_op)
                # Rename legacy index file to index.migrated to prevent zombie resurrection
                migrated_path = self.legacy_json_path.with_name("index.migrated")
                try:
                    self.legacy_json_path.replace(migrated_path)
                except Exception:
                    try:
                        shutil.move(str(self.legacy_json_path), str(migrated_path))
                    except Exception:
                        pass
        except Exception:
            pass  # Legacy migration failure is non-fatal

    def add(
        self,
        path: str,
        mtime: float,
        size: int,
        manifest_hash: str,
        status: str = "staged",
        mode: int = DEFAULT_FILE_MODE,
    ) -> None:
        """Add or update an index entry."""
        norm_path = path.replace("\\", "/")
        def _op(conn: sqlite3.Connection):
            conn.execute(
                """
                INSERT OR REPLACE INTO files (path, mtime, size, manifest_hash, status, mode)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (norm_path, mtime, size, manifest_hash, status, mode),
            )
        self._execute_with_retry(_op)

    def get(self, path: str) -> Optional[IndexRow]:
        """Fetch index row by relative path."""
        norm_path = path.replace("\\", "/")
        def _op(conn: sqlite3.Connection):
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status, mode FROM files WHERE path = ?",
                (norm_path,),
            )
            row = cur.fetchone()
            if row:
                return IndexRow.from_row(row)
            return None
        return self._execute_with_retry(_op)

    def remove(self, path: str) -> bool:
        """Remove a path from the index."""
        norm_path = path.replace("\\", "/")
        def _op(conn: sqlite3.Connection):
            cur = conn.execute("DELETE FROM files WHERE path = ?", (norm_path,))
            return cur.rowcount > 0
        return self._execute_with_retry(_op)

    def clear(self) -> None:
        """Clear all indexed entries."""
        def _op(conn: sqlite3.Connection):
            conn.execute("DELETE FROM files;")
        self._execute_with_retry(_op)

    def entries(self) -> List[IndexRow]:
        """Get all entries sorted by path."""
        def _op(conn: sqlite3.Connection):
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status, mode FROM files ORDER BY path ASC"
            )
            return [IndexRow.from_row(r) for r in cur.fetchall()]
        return self._execute_with_retry(_op)

    def staged_entries(self) -> List[IndexRow]:
        """Get all currently staged entries."""
        def _op(conn: sqlite3.Connection):
            cur = conn.execute(
                "SELECT path, mtime, size, manifest_hash, status, mode FROM files WHERE status = 'staged' ORDER BY path ASC"
            )
            return [IndexRow.from_row(r) for r in cur.fetchall()]
        return self._execute_with_retry(_op)

    @staticmethod
    def is_row_unchanged(
        cached_row: Optional[IndexRow],
        current_mtime: float,
        current_size: int,
        current_mode: Optional[int] = None,
    ) -> bool:
        """Check if cached IndexRow matches current stat without querying SQLite."""
        if not cached_row:
            return False
        time_diff = abs(cached_row.mtime - current_mtime)
        size_match = cached_row.size == current_size
        unchanged = size_match and (time_diff < 1e-4)
        if unchanged and current_mode is not None:
            return (cached_row.mode & 0o777) == (current_mode & 0o777)
        return unchanged

    def is_file_unchanged(self, path: str, current_mtime: float, current_size: int) -> bool:
        """Check if file matches cached mtime and size in index.db without reading disk bytes."""
        row = self.get(path)
        return self.is_row_unchanged(row, current_mtime, current_size)

    def add_batch(
        self,
        entries: List[Union[IndexRow, Dict[str, Any], Tuple[Any, ...]]],
    ) -> None:
        """Add or update multiple index entries in a single atomic transaction."""
        if not entries:
            return

        records = []
        for e in entries:
            if isinstance(e, IndexRow):
                records.append((
                    e.path.replace("\\", "/"),
                    float(e.mtime),
                    int(e.size),
                    str(e.manifest_hash),
                    str(e.status),
                    int(getattr(e, "mode", DEFAULT_FILE_MODE)),
                ))
            elif isinstance(e, dict):
                records.append((
                    str(e["path"]).replace("\\", "/"),
                    float(e["mtime"]),
                    int(e["size"]),
                    str(e.get("manifest_hash", e.get("sha", ""))),
                    str(e.get("status", "staged")),
                    int(e.get("mode", DEFAULT_FILE_MODE)),
                ))
            elif isinstance(e, (tuple, list)):
                p = str(e[0]).replace("\\", "/")
                mt = float(e[1])
                sz = int(e[2])
                mh = str(e[3])
                st = str(e[4]) if len(e) > 4 else "staged"
                md = int(e[5]) if len(e) > 5 else DEFAULT_FILE_MODE
                records.append((p, mt, sz, mh, st, md))

        def _op(conn: sqlite3.Connection):
            conn.executemany(
                """
                INSERT OR REPLACE INTO files (path, mtime, size, manifest_hash, status, mode)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        self._execute_with_retry(_op)

    def update_batch(
        self,
        updates: Union[List[Tuple[str, str]], Dict[str, str]],
    ) -> None:
        """Batch update file status flags in a single transaction."""
        if not updates:
            return
        if isinstance(updates, dict):
            params = [(status, p.replace("\\", "/")) for p, status in updates.items()]
        else:
            params = [(status, p.replace("\\", "/")) for p, status in updates]

        def _op(conn: sqlite3.Connection):
            conn.executemany(
                "UPDATE files SET status = ? WHERE path = ?",
                params,
            )
        self._execute_with_retry(_op)

    def update_status_batch(self, paths: List[str], new_status: str) -> None:
        """Update status of multiple paths in a single transaction."""
        if not paths:
            return
        self.update_batch([(p, new_status) for p in paths])

    def update_status(self, path: str, new_status: str) -> None:
        """Update status flag of a file in the index."""
        norm_path = path.replace("\\", "/")
        def _op(conn: sqlite3.Connection):
            conn.execute(
                "UPDATE files SET status = ? WHERE path = ?",
                (new_status, norm_path),
            )
        self._execute_with_retry(_op)

    def quick_check(self) -> str:
        """Run SQLite PRAGMA quick_check; returns 'ok' or error string."""
        def _op(conn: sqlite3.Connection):
            cur = conn.execute("PRAGMA quick_check;")
            row = cur.fetchone()
            return row[0] if row else "unknown"
        return self._execute_with_retry(_op)

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
        def _op(conn: sqlite3.Connection):
            cur = conn.execute("SELECT COUNT(*) FROM files")
            return int(cur.fetchone()[0])
        return self._execute_with_retry(_op)
