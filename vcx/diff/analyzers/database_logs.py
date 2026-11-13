"""Database and Log analyzer for SQLite, CSV, and log streams."""

from __future__ import annotations
import csv
import io
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class DatabaseLogsAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        if file_name.endswith((".db", ".sqlite", ".sqlite3")) or (
            new_content and new_content.startswith(b"SQLite format 3\000")
        ):
            return self._analyze_sqlite(old_content, new_content, file_name)
        else:
            return self._analyze_text_records(old_content, new_content, file_name)

    def _analyze_sqlite(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_meta = self._get_sqlite_meta(old_content)
        new_meta = self._get_sqlite_meta(new_content)

        facts: Dict[str, Any] = {"table_deltas": {}, "schema_changes": []}
        diff_lines = []

        all_tables = set(old_meta.keys()) | set(new_meta.keys())
        for table in sorted(all_tables):
            o_info = old_meta.get(table, {"count": 0, "columns": []})
            n_info = new_meta.get(table, {"count": 0, "columns": []})

            count_delta = n_info["count"] - o_info["count"]
            if table not in old_meta:
                facts["schema_changes"].append(f"Created table '{table}'")
                diff_lines.append(f"+ TABLE {table} (rows: {n_info['count']})")
            elif table not in new_meta:
                facts["schema_changes"].append(f"Dropped table '{table}'")
                diff_lines.append(f"- TABLE {table}")
            elif count_delta != 0:
                facts["table_deltas"][table] = count_delta
                diff_lines.append(
                    f"~ {table}: {'+' if count_delta > 0 else ''}{count_delta} rows (total: {n_info['count']})"
                )

            if o_info["columns"] != n_info["columns"]:
                added_cols = set(n_info["columns"]) - set(o_info["columns"])
                if added_cols:
                    facts["schema_changes"].append(
                        f"Added columns {sorted(list(added_cols))} to '{table}'"
                    )

        raw_diff = "\n".join(diff_lines) if diff_lines else "SQLite database modified (no row delta)"
        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary="",
            domain_facts=facts,
        )

    def _get_sqlite_meta(self, content: Optional[bytes]) -> Dict[str, Any]:
        if not content:
            return {}
        meta: Dict[str, Any] = {}
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(content)
            temp_path = f.name

        conn = None
        try:
            conn = sqlite3.connect(temp_path, timeout=3.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [row[0] for row in cursor.fetchall()]

            for t in tables:
                escaped_t = t.replace('"', '""')
                try:
                    cursor.execute(f'SELECT count(*) FROM "{escaped_t}";')
                    cnt = cursor.fetchone()[0]
                    cursor.execute(f'PRAGMA table_info("{escaped_t}");')
                    cols = [row[1] for row in cursor.fetchall()]
                    meta[t] = {"count": cnt, "columns": cols}
                except Exception:
                    meta[t] = {"count": 0, "columns": []}
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        return meta

    def _analyze_text_records(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_text = old_content.decode("utf-8", errors="replace") if old_content else ""
        new_text = new_content.decode("utf-8", errors="replace") if new_content else ""

        raw_diff = self.compute_text_diff(old_text, new_text, file_name)

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()

        line_delta = len(new_lines) - len(old_lines)
        facts = {
            "rows_appended": max(0, line_delta),
            "rows_removed": max(0, -line_delta),
            "total_rows": len(new_lines),
        }

        old_meta = {"total_rows": len(old_lines)}
        new_meta = {"total_rows": len(new_lines)}

        # If CSV, parse columns
        if file_name.endswith((".csv", ".tsv")):
            delimiter = "\t" if file_name.endswith(".tsv") else ","
            if old_lines:
                old_meta["columns"] = next(csv.reader([old_lines[0]], delimiter=delimiter), [])
            if new_lines:
                new_meta["columns"] = next(csv.reader([new_lines[0]], delimiter=delimiter), [])
                if "columns" in old_meta and old_meta["columns"] != new_meta["columns"]:
                    facts["column_delta"] = [
                        c for c in new_meta["columns"] if c not in old_meta["columns"]
                    ]

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary="",
            domain_facts=facts,
        )
