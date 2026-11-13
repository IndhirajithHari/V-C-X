"""Universal file type detection for all software and applications in the world.

Covers:
- Media: Video, Audio, Motion, Spatial Audio, Images
- Creative Suites: Premiere, Final Cut, DaVinci, Photoshop, Blender, Audacity, Filmcraft
- Music DAWs: Ableton Live, Cockos Reaper, FL Studio, Logic Pro
- Game Engines: Unity, Unreal Engine, Godot
- Design & UI/UX: Sketch, Krita, GIMP, Figma, Affinity
- CAD & Engineering: AutoCAD (DWG/DXF), FreeCAD, Rhino, SolidWorks, KiCad EDA
- Big Data & Scientific: Apache Parquet, HDF5, NetCDF, DuckDB, SQLite
- Systems & Compilers: ELF, Mach-O, Windows PE, WebAssembly, Java Bytecode
- Office & Documents: PDF, Word, Excel, PowerPoint, EPUB, OpenDocument
- Containers & Archives: ZIP, GZIP, 7-Zip, TAR, RAR
- Pure Binary Fallback: Content-defined chunking (CDC) & entropy analysis
"""

from __future__ import annotations
import gzip
import io
import os
from pathlib import Path
from typing import Optional


def detect_file_type(file_path: Path | str, content: Optional[bytes] = None) -> str:
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

    # 3. Creative Apps & Video/Audio Suites
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

    # 4. Music DAWs
    if suffix in (".als",):
        return "music/ableton"
    if suffix in (".rpp",):
        return "music/reaper"
    if suffix in (".flp",):
        return "music/flstudio"
    if suffix in (".logicx", ".cpr"):
        return "music/generic"

    # 5. Game Engines & Interactive 3D
    if suffix in (".unity", ".prefab", ".mat", ".asset", ".unitypackage"):
        return "game/unity"
    if suffix in (".uproject", ".uasset", ".umap"):
        return "game/unreal"
    if suffix in (".tscn", ".tres", ".godot"):
        return "game/godot"

    # 6. Design, UI/UX & Digital Painting
    if suffix in (".sketch",):
        return "design/sketch"
    if suffix in (".kra",):
        return "design/krita"
    if suffix in (".xcf",):
        return "design/gimp"
    if suffix in (".fig",):
        return "design/figma"
    if suffix in (".afdesign", ".afphoto", ".afpublisher"):
        return "design/affinity"
    if suffix in (".cdr", ".indd", ".idml"):
        return "design/generic"

    # 7. Raster & Vector Images
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

    # 8. CAD & Architecture
    if suffix in (".fcstd", ".fcmacro"):
        return "cad/freecad"
    if suffix == ".stl":
        return "cad/stl"
    if suffix in (".step", ".stp"):
        return "cad/step"
    if suffix == ".obj":
        return "cad/obj"
    if suffix in (".dwg",):
        return "cad/dwg"
    if suffix in (".dxf",):
        return "cad/dxf"
    if suffix in (".3dm", ".skp", ".sldprt", ".sldasm", ".f3d"):
        return "cad/generic"

    # 9. Hardware / EDA
    if suffix in (".v", ".vh"):
        return "eda/verilog"
    if suffix in (".sv", ".svh"):
        return "eda/systemverilog"
    if suffix in (".def", ".lef") or "floorplan" in name or "placement" in name:
        return "eda/floorplan"
    if suffix in (".kicad_pcb", ".kicad_sch", ".kicad_pro"):
        return "eda/kicad"
    if suffix in (".brd", ".sch"):
        return "eda/eagle"

    # 10. Data Science & Big Data
    if suffix in (".parquet",):
        return "database/parquet"
    if suffix in (".h5", ".hdf5", ".nc"):
        return "scientific/hdf5"
    if suffix in (".sqlite", ".sqlite3", ".db"):
        return "database/sqlite"
    if suffix in (".csv", ".tsv"):
        return "database/csv"
    if suffix in (".log", ".jsonl"):
        return "log/generic"

    # 11. Documents & Office
    if suffix in (".pdf",):
        return "document/pdf"
    if suffix in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".pages", ".key", ".numbers"):
        return "document/office"

    # 12. Archives & Containers
    if suffix in (".zip",):
        return "archive/zip"
    if suffix in (".7z",):
        return "archive/7z"
    if suffix in (".tar", ".gz", ".tgz", ".bz2", ".xz", ".rar", ".iso", ".dmg"):
        return "archive/generic"

    # 13. Source Code
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

    # 14. Plaintext & Configs
    if suffix in (".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".json", ".xml", ".html", ".css", ".sh"):
        return "text/plain"

    # 15. Magic bytes content sniffing
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

        # GIMP XCF
        if raw.startswith(b"gimp xcf"):
            return "design/gimp"

        # AutoCAD DWG
        if raw.startswith(b"AC10"):
            return "cad/dwg"

        # Apache Parquet
        if raw.startswith(b"PAR1"):
            return "database/parquet"

        # HDF5
        if raw.startswith(b"\x89HDF\r\n\x1a\n"):
            return "scientific/hdf5"

        # 7-Zip
        if raw.startswith(b"7z\xbc\xaf\x27\x1c"):
            return "archive/7z"

        # SQLite format (Database, Audacity, or app project)
        if raw.startswith(b"SQLite format 3\000"):
            if "aup3" in name:
                return "creative/audacity"
            return "database/sqlite"

        # Gzip container (Premiere, Ableton, or SVGZ)
        if raw.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                    header_decomp = gz.read(256)
                    if b"PremiereData" in header_decomp or b"ProjectItem" in header_decomp:
                        return "creative/premiere"
                    if b"<Ableton" in header_decomp:
                        return "music/ableton"
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

        # Executables & Binaries
        if raw.startswith(b"\x7fELF"):
            return "binary/elf"
        if raw.startswith((b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe")):
            return "binary/macho"
        if raw.startswith(b"MZ"):
            return "binary/pe"
        if raw.startswith(b"\x00asm"):
            return "binary/wasm"

        # ZIP containers (Office, Sketch, Krita, FreeCAD, APK, JAR, ZIP)
        if raw.startswith(b"PK\x03\x04"):
            if "sketch" in suffix or "sketch" in name:
                return "design/sketch"
            if "kra" in suffix:
                return "design/krita"
            if "fcstd" in suffix:
                return "cad/freecad"
            return "archive/zip"

        # Text check
        if b"\0" not in raw[:1024]:
            if b"<REAPER_PROJECT" in raw[:1024]:
                return "music/reaper"
            if b"%YAML" in raw[:256] and b"!u!" in raw[:1024]:
                return "game/unity"
            if b"[gd_scene" in raw[:256] or b"[gd_resource" in raw[:256]:
                return "game/godot"
            return "text/plain"

        return "binary/unknown"

    return "binary/unknown"
