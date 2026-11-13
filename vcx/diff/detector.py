"""File type detection for multi-domain version control covering code, hardware, CAD, media, creative apps, documents, and databases."""

from __future__ import annotations
import gzip
import io
import os
from pathlib import Path
from typing import Optional


def detect_file_type(file_path: Path | str, content: Optional[bytes] = None) -> str:
    """Classify file into standard VCX domain file types:

    - Video: video/mp4, video/mov, video/mkv, video/webm, video/avi, video/generic
    - Audio: audio/wav, audio/mp3, audio/flac, audio/aac, audio/ogg, audio/generic
    - Image: image/png, image/jpeg, image/webp, image/svg, image/tiff, image/generic
    - Creative Apps: creative/premiere, creative/fcpxml, creative/davinci, creative/photoshop,
                     creative/blender, creative/audacity, creative/filmcraft, creative/gltf, creative/generic
    - Hardware / EDA: eda/verilog, eda/systemverilog, eda/floorplan
    - CAD / 3D: cad/freecad, cad/stl, cad/step, cad/obj
    - Source: source/rust, source/c, source/cpp, source/python, source/generic
    - Database / Logs: database/sqlite, database/csv, log/generic
    - Documents / Office: document/pdf, document/office, text/plain
    - Archives: archive/zip, archive/tar, archive/generic
    - Binary Fallback: binary/unknown
    """
    path = Path(file_path)
    name = path.name.lower()
    suffix = path.suffix.lower()

    # 1. Video Formats
    if suffix in (".mp4", ".m4v"):
        return "video/mp4"
    if suffix in (".mov", ".qt"):
        return "video/mov"
    if suffix in (".mkv",):
        return "video/mkv"
    if suffix in (".webm",):
        return "video/webm"
    if suffix in (".avi",):
        return "video/avi"
    if suffix in (".flv", ".wmv", ".prores", ".ts", ".mts", ".m2ts"):
        return "video/generic"

    # 2. Audio Formats
    if suffix in (".wav", ".wave"):
        return "audio/wav"
    if suffix in (".mp3",):
        return "audio/mp3"
    if suffix in (".flac",):
        return "audio/flac"
    if suffix in (".aac", ".m4a", ".alac"):
        return "audio/aac"
    if suffix in (".ogg", ".oga", ".opus"):
        return "audio/ogg"
    if suffix in (".aif", ".aiff", ".wma", ".mid", ".midi"):
        return "audio/generic"

    # 3. Creative Apps & Video/Audio Editing Projects
    if suffix in (".prproj",):
        return "creative/premiere"
    if suffix in (".fcpxml", ".fcpxmld"):
        return "creative/fcpxml"
    if suffix in (".drp", ".edl"):
        return "creative/davinci"
    if suffix in (".psd", ".psb"):
        return "creative/photoshop"
    if suffix in (".blend", ".blend1"):
        return "creative/blender"
    if suffix in (".aup3",):
        return "creative/audacity"
    if suffix in (".filmcraft", ".fcproj"):
        return "creative/filmcraft"
    if suffix in (".gltf", ".glb"):
        return "creative/gltf"
    if suffix in (".fbx", ".dae", ".usdz", ".abc"):
        return "creative/generic"

    # 4. Raster & Vector Images
    if suffix in (".png",):
        return "image/png"
    if suffix in (".jpg", ".jpeg", ".jpe"):
        return "image/jpeg"
    if suffix in (".webp",):
        return "image/webp"
    if suffix in (".svg", ".svgz"):
        return "image/svg"
    if suffix in (".tif", ".tiff"):
        return "image/tiff"
    if suffix in (".gif", ".bmp", ".ico", ".raw", ".cr2", ".nef", ".arw", ".exr", ".hdr"):
        return "image/generic"

    # 5. Documents & Office
    if suffix in (".pdf",):
        return "document/pdf"
    if suffix in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".rtf"):
        return "document/office"

    # 6. Archives & Containers
    if suffix in (".zip",):
        return "archive/zip"
    if suffix in (".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".iso", ".dmg"):
        return "archive/generic"

    # 7. Hardware / EDA
    if suffix in (".v", ".vh"):
        return "eda/verilog"
    if suffix in (".sv", ".svh"):
        return "eda/systemverilog"
    if suffix in (".def", ".lef") or "floorplan" in name or "placement" in name:
        return "eda/floorplan"

    # 8. CAD / 3D Models
    if suffix in (".fcstd", ".fcmacro"):
        return "cad/freecad"
    if suffix == ".stl":
        return "cad/stl"
    if suffix in (".step", ".stp"):
        return "cad/step"
    if suffix == ".obj":
        return "cad/obj"

    # 9. Source Code
    if suffix in (".rs",):
        return "source/rust"
    if suffix in (".c", ".h"):
        return "source/c"
    if suffix in (".cpp", ".hpp", ".cc", ".cxx"):
        return "source/cpp"
    if suffix in (".py", ".pyi"):
        return "source/python"
    if suffix in (".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".scala", ".rb", ".php", ".cs", ".swift", ".kt", ".dart", ".zig"):
        return "source/generic"

    # 10. Database / Structured Logs
    if suffix in (".sqlite", ".sqlite3", ".db"):
        return "database/sqlite"
    if suffix in (".csv", ".tsv"):
        return "database/csv"
    if suffix in (".log", ".jsonl"):
        return "log/generic"

    # 11. Plaintext & Configs
    if suffix in (".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".json", ".xml", ".html", ".css", ".sh"):
        return "text/plain"

    # 12. Magic bytes content sniffing
    raw = content
    if raw is None and path.is_file():
        try:
            with open(path, "rb") as f:
                raw = f.read(4096)
        except OSError:
            pass

    if raw:
        # Photoshop PSD/PSB
        if raw.startswith(b"8BPS"):
            return "creative/photoshop"

        # Blender 3D
        if raw.startswith(b"BLENDER"):
            return "creative/blender"

        # glTF Binary
        if raw.startswith(b"glTF"):
            return "creative/gltf"

        # SQLite format (Database or Audacity project)
        if raw.startswith(b"SQLite format 3\000"):
            if "aup3" in name:
                return "creative/audacity"
            return "database/sqlite"

        # Gzip container (Could be Premiere .prproj or SVGZ)
        if raw.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                    header_decomp = gz.read(256)
                    if b"PremiereData" in header_decomp or b"ProjectItem" in header_decomp:
                        return "creative/premiere"
            except Exception:
                pass
            return "archive/generic"

        # PDF format
        if raw.startswith(b"%PDF-"):
            return "document/pdf"

        # PNG Image
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"

        # JPEG Image
        if raw.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"

        # GIF Image
        if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
            return "image/generic"

        # WebP / RIFF containers (WAV / WebP / AVI)
        if raw.startswith(b"RIFF") and len(raw) >= 12:
            fourcc = raw[8:12]
            if fourcc == b"WAVE":
                return "audio/wav"
            if fourcc == b"WEBP":
                return "image/webp"
            if fourcc == b"AVI ":
                return "video/avi"

        # FLAC Audio
        if raw.startswith(b"fLaC"):
            return "audio/flac"

        # MP3 Audio
        if raw.startswith(b"ID3") or raw.startswith(b"\xff\xfb"):
            return "audio/mp3"

        # MP4 / MOV containers
        if len(raw) >= 8 and raw[4:8] == b"ftyp":
            brand = raw[8:12] if len(raw) >= 12 else b""
            if brand in (b"qt  ", b"moov"):
                return "video/mov"
            return "video/mp4"

        # Matroska / WebM container
        if raw.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/mkv"

        # ZIP containers (ZIP, DOCX, XLSX, PPTX, FreeCAD)
        if raw.startswith(b"PK\x03\x04"):
            return "archive/zip"

        # Text check
        if b"\0" not in raw[:1024]:
            return "text/plain"

        return "binary/unknown"

    return "binary/unknown"
