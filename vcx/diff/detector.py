"""Universal file type detection matrix covering all software and applications in the world.

Catalog spans 500+ standard extensions and magic byte signatures across:
- Video, Motion, VFX & Film Editing
- Audio, Sound Design, Acoustics & DAWs
- Graphic Design, Raster, Vector, Textures & RAW Photography
- 3D Modeling, CAD, BIM, CAM & Architecture
- Hardware Engineering, EDA, RTL, PCB & Semiconductors
- Game Engines, Interactive 3D, Prefabs & Shaders
- Documents, Publishing, Typography & Office Suites
- Programming Languages, Web, Scripts & Interface Schemata
- Big Data, Machine Learning, Databases, GIS & Scientific Computing
- Archives, Containers, Disk Images & Package Managers
- Systems, Executables, Firmware, Bytecode & FPGA Bitstreams
"""

from __future__ import annotations
import gzip
import io
import os
from pathlib import Path
from typing import Dict, Optional

# Exhaustive dictionary mapping 500+ file extensions to canonical VCX domain types
UNIVERSAL_EXTENSION_MAP: Dict[str, str] = {
    # -------------------------------------------------------------------------
    # 1. Video, Motion, VFX & Film Editing
    # -------------------------------------------------------------------------
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/mov",
    ".qt": "video/mov",
    ".mkv": "video/mkv",
    ".webm": "video/webm",
    ".avi": "video/avi",
    ".wmv": "video/generic",
    ".flv": "video/generic",
    ".f4v": "video/generic",
    ".vob": "video/generic",
    ".ogv": "video/generic",
    ".drc": "video/generic",
    ".mng": "video/generic",
    ".mts": "video/generic",
    ".m2ts": "video/generic",
    ".ts": "video/generic",
    ".prores": "video/generic",
    ".dnxhr": "video/generic",
    ".dnxhd": "video/generic",
    ".mxf": "video/generic",
    ".roq": "video/generic",
    ".yuv": "video/generic",
    ".rm": "video/generic",
    ".rmvb": "video/generic",
    ".asf": "video/generic",
    ".amv": "video/generic",
    ".mpg": "video/generic",
    ".mpeg": "video/generic",
    ".m2v": "video/generic",
    ".3gp": "video/generic",
    ".3g2": "video/generic",
    ".svi": "video/generic",
    ".prproj": "creative/premiere",
    ".fcpxml": "creative/fcpxml",
    ".fcpxmld": "creative/fcpxml",
    ".drp": "creative/davinci",
    ".edl": "creative/davinci",
    ".aep": "creative/generic",
    ".aet": "creative/generic",
    ".nk": "creative/generic",
    ".nkn": "creative/generic",
    ".hip": "creative/generic",
    ".motn": "creative/generic",
    ".veg": "creative/generic",
    ".vpj": "creative/generic",
    ".kdenlive": "creative/generic",
    ".mlt": "creative/generic",
    ".braw": "video/generic",
    ".r3d": "video/generic",
    ".ari": "video/generic",
    ".filmcraft": "creative/filmcraft",
    ".fcproj": "creative/filmcraft",

    # -------------------------------------------------------------------------
    # 2. Audio, Sound Design, Acoustics & DAWs
    # -------------------------------------------------------------------------
    ".wav": "audio/wav",
    ".wave": "audio/wav",
    ".flac": "audio/flac",
    ".mp3": "audio/mp3",
    ".aac": "audio/aac",
    ".m4a": "audio/aac",
    ".alac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wma": "audio/generic",
    ".aiff": "audio/generic",
    ".aif": "audio/generic",
    ".aifc": "audio/generic",
    ".pcm": "audio/generic",
    ".dsd": "audio/generic",
    ".dsf": "audio/generic",
    ".dff": "audio/generic",
    ".mid": "audio/generic",
    ".midi": "audio/generic",
    ".mod": "audio/generic",
    ".s3m": "audio/generic",
    ".xm": "audio/generic",
    ".it": "audio/generic",
    ".als": "music/ableton",
    ".flp": "music/flstudio",
    ".rpp": "music/reaper",
    ".logicx": "music/logic",
    ".cpr": "music/generic",
    ".npr": "music/generic",
    ".ptx": "music/generic",
    ".ptf": "music/generic",
    ".band": "music/generic",
    ".aup3": "creative/audacity",
    ".sesx": "music/generic",
    ".cwb": "music/generic",
    ".sf2": "audio/generic",
    ".sfz": "audio/generic",
    ".nki": "audio/generic",
    ".ape": "audio/generic",
    ".wv": "audio/generic",
    ".mka": "audio/generic",
    ".ac3": "audio/generic",
    ".eac3": "audio/generic",
    ".dts": "audio/generic",

    # -------------------------------------------------------------------------
    # 3. Graphics, Raster, Vector, Textures & RAW Photography
    # -------------------------------------------------------------------------
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/generic",
    ".bmp": "image/generic",
    ".dib": "image/generic",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".svg": "image/svg",
    ".svgz": "image/svg",
    ".eps": "image/generic",
    ".ai": "image/generic",
    ".psd": "creative/photoshop",
    ".psb": "creative/photoshop",
    ".xcf": "design/gimp",
    ".kra": "design/krita",
    ".ora": "design/generic",
    ".pdn": "design/generic",
    ".sketch": "design/sketch",
    ".fig": "design/figma",
    ".afdesign": "design/affinity",
    ".afphoto": "design/affinity",
    ".afpublisher": "design/affinity",
    ".cdr": "design/generic",
    ".ico": "image/generic",
    ".cur": "image/generic",
    ".hdr": "image/generic",
    ".exr": "image/generic",
    ".tga": "image/generic",
    ".dds": "image/generic",
    ".heic": "image/generic",
    ".heif": "image/generic",
    ".avif": "image/generic",
    ".raw": "image/generic",
    ".cr2": "image/generic",
    ".cr3": "image/generic",
    ".nef": "image/generic",
    ".nrw": "image/generic",
    ".arw": "image/generic",
    ".srf": "image/generic",
    ".sr2": "image/generic",
    ".dng": "image/generic",
    ".rw2": "image/generic",
    ".orf": "image/generic",
    ".pef": "image/generic",
    ".raf": "image/generic",
    ".pcx": "image/generic",
    ".pbm": "image/generic",
    ".pgm": "image/generic",
    ".ppm": "image/generic",
    ".pnm": "image/generic",

    # -------------------------------------------------------------------------
    # 4. 3D Modeling, CAD, BIM, CAM & Architecture
    # -------------------------------------------------------------------------
    ".step": "cad/step",
    ".stp": "cad/step",
    ".iges": "cad/generic",
    ".igs": "cad/generic",
    ".brep": "cad/generic",
    ".fcstd": "cad/freecad",
    ".fcmacro": "cad/freecad",
    ".dwg": "cad/dwg",
    ".dxf": "cad/dxf",
    ".stl": "cad/stl",
    ".obj": "cad/obj",
    ".ply": "cad/generic",
    ".3ds": "cad/generic",
    ".max": "cad/generic",
    ".fbx": "creative/generic",
    ".blend": "creative/blender",
    ".blend1": "creative/blender",
    ".c4d": "creative/generic",
    ".ma": "creative/generic",
    ".mb": "creative/generic",
    ".dae": "creative/generic",
    ".gltf": "creative/gltf",
    ".glb": "creative/gltf",
    ".usda": "creative/generic",
    ".usdc": "creative/generic",
    ".usdz": "creative/generic",
    ".abc": "creative/generic",
    ".ifc": "cad/generic",
    ".rvt": "cad/generic",
    ".rfa": "cad/generic",
    ".skp": "cad/generic",
    ".3dm": "cad/generic",
    ".sldprt": "cad/generic",
    ".sldasm": "cad/generic",
    ".slddrw": "cad/generic",
    ".catpart": "cad/generic",
    ".catproduct": "cad/generic",
    ".catdrawing": "cad/generic",
    ".prt": "cad/generic",
    ".asm": "cad/generic",
    ".par": "cad/generic",
    ".psm": "cad/generic",
    ".ipt": "cad/generic",
    ".iam": "cad/generic",
    ".idw": "cad/generic",
    ".f3d": "cad/generic",
    ".scad": "cad/generic",
    ".off": "cad/generic",
    ".x3d": "cad/generic",
    ".wrl": "cad/generic",
    ".vrml": "cad/generic",
    ".dgn": "cad/generic",
    ".sat": "cad/generic",
    ".x_t": "cad/generic",
    ".x_b": "cad/generic",
    ".wire": "cad/generic",
    ".jt": "cad/generic",

    # -------------------------------------------------------------------------
    # 5. Hardware Engineering, EDA, RTL, PCB & Semiconductors
    # -------------------------------------------------------------------------
    ".v": "eda/verilog",
    ".vh": "eda/verilog",
    ".sv": "eda/systemverilog",
    ".svh": "eda/systemverilog",
    ".vhd": "eda/generic",
    ".vhdl": "eda/generic",
    ".vlg": "eda/verilog",
    ".def": "eda/floorplan",
    ".lef": "eda/floorplan",
    ".gds": "eda/generic",
    ".gds2": "eda/generic",
    ".oasis": "eda/generic",
    ".oas": "eda/generic",
    ".sp": "eda/generic",
    ".cir": "eda/generic",
    ".net": "eda/generic",
    ".kicad_pcb": "eda/kicad",
    ".kicad_sch": "eda/kicad",
    ".kicad_pro": "eda/kicad",
    ".kicad_mod": "eda/kicad",
    ".kicad_wks": "eda/kicad",
    ".brd": "eda/eagle",
    ".sch": "eda/eagle",
    ".lbr": "eda/eagle",
    ".gbr": "eda/generic",
    ".gerber": "eda/generic",
    ".drl": "eda/generic",
    ".sdc": "eda/generic",
    ".spef": "eda/generic",
    ".vcd": "log/generic",

    # -------------------------------------------------------------------------
    # 6. Game Engines, Interactive 3D, Prefabs & Shaders
    # -------------------------------------------------------------------------
    ".unity": "game/unity",
    ".prefab": "game/unity",
    ".mat": "game/unity",
    ".asset": "game/unity",
    ".unitypackage": "game/unity",
    ".anim": "game/unity",
    ".controller": "game/unity",
    ".uproject": "game/unreal",
    ".uasset": "game/unreal",
    ".umap": "game/unreal",
    ".ubulk": "game/unreal",
    ".uexp": "game/unreal",
    ".tscn": "game/godot",
    ".tres": "game/godot",
    ".gd": "game/godot",
    ".godot": "game/godot",
    ".import": "game/godot",
    ".shader": "source/generic",
    ".hlsl": "source/generic",
    ".glsl": "source/generic",
    ".frag": "source/generic",
    ".vert": "source/generic",
    ".comp": "source/generic",
    ".geom": "source/generic",
    ".spv": "binary/generic",
    ".cg": "source/generic",
    ".metal": "source/generic",
    ".wgsl": "source/generic",

    # -------------------------------------------------------------------------
    # 7. Documents, Publishing, Typography & Office Suites
    # -------------------------------------------------------------------------
    ".pdf": "document/pdf",
    ".doc": "document/office",
    ".docx": "document/office",
    ".docm": "document/office",
    ".dot": "document/office",
    ".dotx": "document/office",
    ".dotm": "document/office",
    ".rtf": "document/office",
    ".odt": "document/office",
    ".ott": "document/office",
    ".xls": "document/office",
    ".xlsx": "document/office",
    ".xlsm": "document/office",
    ".xlsb": "document/office",
    ".xlt": "document/office",
    ".xltx": "document/office",
    ".ods": "document/office",
    ".ots": "document/office",
    ".ppt": "document/office",
    ".pptx": "document/office",
    ".pptm": "document/office",
    ".pps": "document/office",
    ".ppsx": "document/office",
    ".odp": "document/office",
    ".otp": "document/office",
    ".pages": "document/office",
    ".key": "document/office",
    ".numbers": "document/office",
    ".epub": "document/office",
    ".mobi": "document/office",
    ".azw": "document/office",
    ".azw3": "document/office",
    ".djvu": "document/office",
    ".tex": "text/plain",
    ".latex": "text/plain",
    ".typ": "text/plain",
    ".indd": "design/generic",
    ".idml": "design/generic",
    ".qxd": "design/generic",
    ".xps": "document/pdf",
    ".oxps": "document/pdf",

    # -------------------------------------------------------------------------
    # 8. Programming Languages, Web, Scripts & Interface Schemata
    # -------------------------------------------------------------------------
    ".rs": "source/rust",
    ".c": "source/c",
    ".h": "source/c",
    ".cpp": "source/cpp",
    ".hpp": "source/cpp",
    ".cc": "source/cpp",
    ".hh": "source/cpp",
    ".cxx": "source/cpp",
    ".hxx": "source/cpp",
    ".py": "source/python",
    ".pyi": "source/python",
    ".pyw": "source/python",
    ".pyx": "source/python",
    ".js": "source/generic",
    ".mjs": "source/generic",
    ".cjs": "source/generic",
    ".jsx": "source/generic",
    ".ts": "source/generic",
    ".mts": "source/generic",
    ".cts": "source/generic",
    ".tsx": "source/generic",
    ".go": "source/generic",
    ".java": "source/generic",
    ".kt": "source/generic",
    ".kts": "source/generic",
    ".scala": "source/generic",
    ".sc": "source/generic",
    ".swift": "source/generic",
    ".m": "source/generic",
    ".mm": "source/generic",
    ".cs": "source/generic",
    ".vb": "source/generic",
    ".fs": "source/generic",
    ".fsx": "source/generic",
    ".rb": "source/generic",
    ".rbw": "source/generic",
    ".php": "source/generic",
    ".phtml": "source/generic",
    ".lua": "source/generic",
    ".pl": "source/generic",
    ".pm": "source/generic",
    ".t": "source/generic",
    ".sh": "source/generic",
    ".bash": "source/generic",
    ".zsh": "source/generic",
    ".fish": "source/generic",
    ".bat": "source/generic",
    ".cmd": "source/generic",
    ".ps1": "source/generic",
    ".psm1": "source/generic",
    ".dart": "source/generic",
    ".zig": "source/generic",
    ".nim": "source/generic",
    ".clj": "source/generic",
    ".cljs": "source/generic",
    ".edn": "source/generic",
    ".ex": "source/generic",
    ".exs": "source/generic",
    ".erl": "source/generic",
    ".hrl": "source/generic",
    ".hs": "source/generic",
    ".lhs": "source/generic",
    ".ml": "source/generic",
    ".mli": "source/generic",
    ".r": "source/generic",
    ".rmd": "source/generic",
    ".jl": "source/generic",
    ".sql": "source/generic",
    ".html": "source/generic",
    ".htm": "source/generic",
    ".xhtml": "source/generic",
    ".css": "source/generic",
    ".scss": "source/generic",
    ".sass": "source/generic",
    ".less": "source/generic",
    ".vue": "source/generic",
    ".svelte": "source/generic",
    ".graphql": "source/generic",
    ".gql": "source/generic",
    ".proto": "source/generic",
    ".fbs": "source/generic",
    ".thrift": "source/generic",
    ".wasm": "binary/wasm",
    ".wat": "text/plain",

    # -------------------------------------------------------------------------
    # 9. Big Data, Machine Learning, Databases, GIS & Scientific Computing
    # -------------------------------------------------------------------------
    ".parquet": "database/parquet",
    ".arrow": "database/columnar",
    ".feather": "database/columnar",
    ".orc": "database/columnar",
    ".avro": "database/columnar",
    ".h5": "scientific/hdf5",
    ".hdf5": "scientific/hdf5",
    ".nc": "scientific/hdf5",
    ".nc4": "scientific/hdf5",
    ".cdl": "scientific/hdf5",
    ".fits": "scientific/fits",
    ".fit": "scientific/fits",
    ".fts": "scientific/fits",
    ".mat": "scientific/matlab",
    ".sqlite": "database/sqlite",
    ".sqlite3": "database/sqlite",
    ".db": "database/sqlite",
    ".db3": "database/sqlite",
    ".s3db": "database/sqlite",
    ".sl3": "database/sqlite",
    ".duckdb": "database/sqlite",
    ".kdb": "database/columnar",
    ".rdata": "scientific/generic",
    ".rds": "scientific/generic",
    ".dta": "scientific/generic",
    ".sav": "scientific/generic",
    ".sas7bdat": "scientific/generic",
    ".gpkg": "database/sqlite",
    ".geojson": "gis/spatial",
    ".shp": "gis/spatial",
    ".shx": "gis/spatial",
    ".dbf": "database/generic",
    ".prj": "text/plain",
    ".kml": "gis/spatial",
    ".kmz": "archive/zip",
    ".las": "gis/spatial",
    ".laz": "gis/spatial",
    ".geotiff": "image/tiff",
    ".onnx": "binary/generic",
    ".pt": "binary/generic",
    ".pth": "binary/generic",
    ".safetensors": "binary/generic",
    ".gguf": "binary/generic",
    ".csv": "database/csv",
    ".tsv": "database/csv",
    ".log": "log/generic",
    ".jsonl": "log/generic",
    ".ndjson": "log/generic",

    # -------------------------------------------------------------------------
    # 10. Archives, Containers, Disk Images & Package Managers
    # -------------------------------------------------------------------------
    ".zip": "archive/zip",
    ".zipx": "archive/zip",
    ".tar": "archive/generic",
    ".gz": "archive/generic",
    ".tgz": "archive/generic",
    ".bz2": "archive/generic",
    ".tbz2": "archive/generic",
    ".xz": "archive/generic",
    ".txz": "archive/generic",
    ".zst": "archive/generic",
    ".tzst": "archive/generic",
    ".7z": "archive/7z",
    ".rar": "archive/generic",
    ".cab": "archive/generic",
    ".iso": "archive/generic",
    ".img": "archive/generic",
    ".dmg": "archive/generic",
    ".vdi": "archive/generic",
    ".vmdk": "archive/generic",
    ".qcow2": "archive/generic",
    ".apk": "archive/zip",
    ".aab": "archive/zip",
    ".xapk": "archive/zip",
    ".ipa": "archive/zip",
    ".deb": "archive/generic",
    ".rpm": "archive/generic",
    ".appimage": "binary/elf",
    ".flatpak": "archive/generic",
    ".snap": "archive/generic",
    ".whl": "archive/zip",
    ".gem": "archive/generic",
    ".crx": "archive/zip",
    ".xpi": "archive/zip",
    ".nupkg": "archive/zip",
    ".jar": "archive/zip",
    ".war": "archive/zip",
    ".ear": "archive/zip",

    # -------------------------------------------------------------------------
    # 11. Systems, Executables, Firmware, Bytecode & Bitstreams
    # -------------------------------------------------------------------------
    ".exe": "binary/pe",
    ".dll": "binary/pe",
    ".sys": "binary/pe",
    ".so": "binary/elf",
    ".dylib": "binary/macho",
    ".elf": "binary/elf",
    ".class": "binary/generic",
    ".dex": "binary/generic",
    ".o": "binary/generic",
    ".a": "binary/generic",
    ".lib": "binary/generic",
    ".hex": "text/plain",
    ".rom": "binary/generic",
    ".firmware": "binary/generic",
    ".bit": "binary/generic",
    ".bin": "binary/generic",
    ".msi": "archive/generic",
    ".drv": "binary/pe",
    ".ocx": "binary/pe",
    ".efi": "binary/pe",
    ".ko": "binary/elf",

    # -------------------------------------------------------------------------
    # 12. Plaintext, Markup, Configs & Metadata
    # -------------------------------------------------------------------------
    ".md": "text/plain",
    ".markdown": "text/plain",
    ".txt": "text/plain",
    ".rst": "text/plain",
    ".asciidoc": "text/plain",
    ".adoc": "text/plain",
    ".yaml": "text/plain",
    ".yml": "text/plain",
    ".toml": "text/plain",
    ".ini": "text/plain",
    ".conf": "text/plain",
    ".cfg": "text/plain",
    ".env": "text/plain",
    ".json": "text/plain",
    ".json5": "text/plain",
    ".xml": "text/plain",

    # -------------------------------------------------------------------------
    # 13. Typography & Fonts
    # -------------------------------------------------------------------------
    ".ttf": "binary/generic",
    ".otf": "binary/generic",
    ".woff": "binary/generic",
    ".woff2": "binary/generic",
    ".eot": "binary/generic",
    ".fon": "binary/generic",
    ".fnt": "binary/generic",
}


def detect_file_type(file_path: Path | str, content: Optional[bytes] = None) -> str:
    """Classify any file in the world into standard VCX domain file types."""
    path = Path(file_path)
    name = path.name.lower()
    suffix = path.suffix.lower()

    # Special name-based rules (e.g. semiconductor floorplans)
    if suffix in (".def", ".lef") or (suffix in (".json", ".yaml", ".yml") and ("floorplan" in name or "placement" in name)):
        return "eda/floorplan"

    # Fast 500+ extension lookup
    if suffix in UNIVERSAL_EXTENSION_MAP:
        resolved = UNIVERSAL_EXTENSION_MAP[suffix]
        # Allow magic-byte sniffer to refine generic categories if content is available
        if content is None and not path.is_file():
            return resolved
        if resolved not in ("archive/generic", "binary/generic", "image/generic", "video/generic", "audio/generic"):
            return resolved

    # Magic bytes content sniffing
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

    # Fallback to map if available
    if suffix in UNIVERSAL_EXTENSION_MAP:
        return UNIVERSAL_EXTENSION_MAP[suffix]

    return "binary/unknown"
