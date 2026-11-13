"""File type detection for multi-domain version control."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional


def detect_file_type(file_path: Path | str, content: Optional[bytes] = None) -> str:
    """Classify file into standard VCX domain file types:

    - source/rust, source/c, source/python, source/generic
    - eda/verilog, eda/systemverilog, eda/floorplan
    - cad/freecad, cad/stl, cad/step, cad/obj
    - database/sqlite, database/csv
    - log/generic
    - binary/unknown
    """
    path = Path(file_path)
    name = path.name.lower()
    suffix = path.suffix.lower()

    # Hardware / EDA types
    if suffix in (".v", ".vh"):
        return "eda/verilog"
    if suffix in (".sv", ".svh"):
        return "eda/systemverilog"
    if suffix in (".def", ".lef") or "floorplan" in name or "placement" in name:
        return "eda/floorplan"

    # CAD / 3D model types
    if suffix in (".fcstd", ".fcproj", ".fcmacro"):
        return "cad/freecad"
    if suffix == ".stl":
        return "cad/stl"
    if suffix in (".step", ".stp"):
        return "cad/step"
    if suffix == ".obj":
        return "cad/obj"

    # Source code
    if suffix in (".rs",):
        return "source/rust"
    if suffix in (".c", ".h"):
        return "source/c"
    if suffix in (".cpp", ".hpp", ".cc", ".cxx"):
        return "source/cpp"
    if suffix in (".py", ".pyi"):
        return "source/python"
    if suffix in (".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".scala", ".rb"):
        return "source/generic"

    # Database / Structured Data / Logs
    if suffix in (".sqlite", ".sqlite3", ".db"):
        return "database/sqlite"
    if suffix in (".csv", ".tsv"):
        return "database/csv"
    if suffix in (".log", ".jsonl"):
        return "log/generic"

    # Check content if provided
    if content:
        # SQLite header check
        if content.startswith(b"SQLite format 3\000"):
            return "database/sqlite"
        # Binary check (null bytes or high non-ascii ratio)
        if b"\0" in content[:1024]:
            return "binary/unknown"

    # Inspect file on disk if exists and no content was passed
    if content is None and path.is_file():
        try:
            with open(path, "rb") as f:
                header = f.read(1024)
                if header.startswith(b"SQLite format 3\000"):
                    return "database/sqlite"
                if b"\0" in header:
                    return "binary/unknown"
        except OSError:
            pass

    return "binary/unknown"
