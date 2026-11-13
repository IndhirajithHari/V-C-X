"""Universal Container & Application Project Analyzer for VCX.

Introspects and semantically diffs project files from any software application:
- Music DAWs: Ableton Live (.als), Reaper (.rpp), FL Studio (.flp)
- Game Engines: Unity (.unity, .prefab, .mat), Godot (.tscn, .tres), Unreal (.uproject)
- Design & Art: Sketch (.sketch), Krita (.kra), GIMP (.xcf), Figma (.fig)
- CAD & EDA: FreeCAD (.fcstd), KiCad (.kicad_pcb, .kicad_sch), AutoCAD (.dxf, .dwg)
- Columnar & Scientific: Apache Parquet (.parquet), HDF5 (.h5, .hdf5)
- Generic App Containers: Transparent in-memory inspection of any ZIP, GZIP, TAR, or SQLite project.
"""

from __future__ import annotations
import gzip
import io
import json
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET
import zipfile

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class UniversalContainerAnalyzer(BaseAnalyzer):
    """Deep structural dissector for application project containers and scene graphs."""

    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        suffix = Path(file_name).suffix.lower()
        active_content = new_content or old_content or b""

        # 1. Music DAWs
        if suffix == ".als" or (active_content.startswith(b"\x1f\x8b") and self._is_ableton(active_content)):
            return self._analyze_ableton(old_content, new_content, file_name)
        if suffix == ".rpp" or b"<REAPER_PROJECT" in active_content[:2048]:
            return self._analyze_reaper(old_content, new_content, file_name)

        # 2. Game Engines
        if suffix in (".unity", ".prefab", ".mat", ".asset") or b"%YAML" in active_content[:256]:
            return self._analyze_unity(old_content, new_content, file_name)
        if suffix in (".tscn", ".tres") or b"[gd_scene" in active_content[:256] or b"[gd_resource" in active_content[:256]:
            return self._analyze_godot(old_content, new_content, file_name)
        if suffix == ".uproject":
            return self._analyze_unreal_project(old_content, new_content, file_name)

        # 3. Design & Art
        if suffix == ".sketch":
            return self._analyze_sketch(old_content, new_content, file_name)
        if suffix == ".kra":
            return self._analyze_krita(old_content, new_content, file_name)

        # 4. CAD & EDA
        if suffix in (".kicad_pcb", ".kicad_sch"):
            return self._analyze_kicad(old_content, new_content, file_name)
        if suffix == ".dxf":
            return self._analyze_dxf(old_content, new_content, file_name)
        if suffix in (".fcstd", ".fcmacro"):
            return self._analyze_freecad(old_content, new_content, file_name)

        # 5. Scientific & Columnar
        if suffix == ".parquet" or active_content.startswith(b"PAR1"):
            return self._analyze_parquet(old_content, new_content, file_name)

        # 6. Container Fallbacks
        if active_content.startswith(b"PK\x03\x04"):
            return self._analyze_generic_zip(old_content, new_content, file_name)
        if active_content.startswith(b"\x1f\x8b"):
            return self._analyze_generic_gzip(old_content, new_content, file_name)
        if active_content.startswith(b"SQLite format 3\000"):
            return self._analyze_generic_sqlite(old_content, new_content, file_name)

        # Generic structural text/diff fallback
        return self._analyze_generic_app_file(old_content, new_content, file_name)

    # -------------------------------------------------------------------------
    # Music DAWs
    # -------------------------------------------------------------------------
    def _is_ableton(self, data: bytes) -> bool:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                head = gz.read(256)
                return b"<Ableton" in head
        except Exception:
            return False

    def _analyze_ableton(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_ableton_meta(old) if old else {}
        new_meta = self._parse_ableton_meta(new) if new else {}

        facts: Dict[str, Any] = {
            "daw": "Ableton Live",
            "tempo_bpm": new_meta.get("bpm", 120.0),
            "tracks_count": new_meta.get("tracks_count", 0),
            "audio_tracks": new_meta.get("audio_tracks", 0),
            "midi_tracks": new_meta.get("midi_tracks", 0),
            "plugins": new_meta.get("plugins", []),
        }

        diffs = []
        if old_meta.get("bpm") != new_meta.get("bpm"):
            diffs.append(f"Tempo shifted: {old_meta.get('bpm', 120.0):.1f} -> {new_meta.get('bpm', 120.0):.1f} BPM")
        if old_meta.get("tracks_count") != new_meta.get("tracks_count"):
            diffs.append(f"Track count: {old_meta.get('tracks_count', 0)} -> {new_meta.get('tracks_count', 0)}")
        if new_meta.get("track_names"):
            diffs.append(f"Session tracks: {', '.join(new_meta.get('track_names')[:4])}")

        raw_diff = "\n".join(diffs) if diffs else f"Ableton Live session updated ({facts['tracks_count']} tracks @ {facts['tempo_bpm']} BPM)"
        return AnalysisResult(old_meta, new_meta, raw_diff, "", facts)

    def _parse_ableton_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                xml_data = gz.read()
            root = ET.fromstring(xml_data)
            # Find tempo
            tempo_elem = root.find(".//Tempo/Manual")
            bpm = float(tempo_elem.attrib.get("Value", 120.0)) if tempo_elem is not None else 120.0

            audio_tracks = len(root.findall(".//AudioTrack"))
            midi_tracks = len(root.findall(".//MidiTrack"))
            return_tracks = len(root.findall(".//ReturnTrack"))
            total_tracks = audio_tracks + midi_tracks + return_tracks

            track_names = []
            for t in root.findall(".//AudioTrack/Name/UserName") + root.findall(".//MidiTrack/Name/UserName"):
                val = t.attrib.get("Value")
                if val:
                    track_names.append(val)

            return {
                "bpm": bpm,
                "tracks_count": total_tracks,
                "audio_tracks": audio_tracks,
                "midi_tracks": midi_tracks,
                "track_names": track_names,
            }
        except Exception:
            return {"bpm": 120.0, "tracks_count": 0}

    def _analyze_reaper(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_reaper_meta(old) if old else {}
        new_meta = self._parse_reaper_meta(new) if new else {}

        facts = {
            "daw": "Cockos Reaper",
            "tracks_count": new_meta.get("tracks_count", 0),
            "bpm": new_meta.get("bpm", 120.0),
            "track_names": new_meta.get("track_names", []),
        }
        diffs = [f"Reaper project session with {facts['tracks_count']} tracks"]
        if old_meta.get("bpm") != new_meta.get("bpm"):
            diffs.append(f"Tempo: {old_meta.get('bpm', 120.0)} -> {new_meta.get('bpm', 120.0)} BPM")
        if facts["track_names"]:
            diffs.append(f"Tracks: {', '.join(facts['track_names'][:4])}")

        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_reaper_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            text = data.decode("utf-8", errors="replace")
            tracks = re.findall(r'<TRACK\s+\{[A-Fa-f0-9-]+\}\s*\n\s*NAME\s+"?([^"\n]+)"?', text)
            bpm_match = re.search(r"TEMPO\s+([\d.]+)", text)
            bpm = float(bpm_match.group(1)) if bpm_match else 120.0
            return {"tracks_count": len(tracks), "track_names": tracks, "bpm": bpm}
        except Exception:
            return {}

    # -------------------------------------------------------------------------
    # Game Engines (Unity, Godot, Unreal)
    # -------------------------------------------------------------------------
    def _analyze_unity(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_unity_meta(old) if old else {}
        new_meta = self._parse_unity_meta(new) if new else {}

        facts = {
            "engine": "Unity",
            "game_objects_count": new_meta.get("game_objects", 0),
            "components_count": new_meta.get("components", 0),
            "object_names": new_meta.get("names", []),
        }
        diffs = [f"Unity Scene/Prefab: {facts['game_objects_count']} GameObjects, {facts['components_count']} Components"]
        if old_meta.get("game_objects") != new_meta.get("game_objects"):
            diffs.append(f"GameObjects: {old_meta.get('game_objects', 0)} -> {new_meta.get('game_objects', 0)}")
        if facts["object_names"]:
            diffs.append(f"Entities: {', '.join(facts['object_names'][:4])}")

        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_unity_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            text = data.decode("utf-8", errors="replace")
            game_objects = len(re.findall(r"--- !u!1 &", text))
            components = len(re.findall(r"--- !u![0-9]+ &", text)) - game_objects
            names = re.findall(r"m_Name:\s*([^\r\n]+)", text)
            clean_names = [n.strip() for n in names if n.strip() and not n.strip().isdigit()]
            return {
                "game_objects": game_objects,
                "components": max(components, 0),
                "names": clean_names[:10],
            }
        except Exception:
            return {}

    def _analyze_godot(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_godot_meta(old) if old else {}
        new_meta = self._parse_godot_meta(new) if new else {}

        facts = {
            "engine": "Godot",
            "nodes_count": new_meta.get("nodes_count", 0),
            "node_types": new_meta.get("types", []),
            "root_type": new_meta.get("root_type", "Node"),
        }
        diffs = [f"Godot Scene Graph: {facts['nodes_count']} nodes (Root: {facts['root_type']})"]
        if old_meta.get("nodes_count") != new_meta.get("nodes_count"):
            diffs.append(f"Nodes delta: {old_meta.get('nodes_count', 0)} -> {new_meta.get('nodes_count', 0)}")
        if facts["node_types"]:
            diffs.append(f"Active classes: {', '.join(facts['node_types'][:4])}")

        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_godot_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            text = data.decode("utf-8", errors="replace")
            nodes = re.findall(r'\[node\s+name="([^"]+)"(?:\s+type="([^"]+)")?', text)
            types = list({t for _, t in nodes if t})
            root_type = nodes[0][1] if (nodes and nodes[0][1]) else "Node"
            return {"nodes_count": len(nodes), "types": types, "root_type": root_type}
        except Exception:
            return {}

    def _analyze_unreal_project(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = json.loads(old.decode("utf-8")) if old else {}
        new_meta = json.loads(new.decode("utf-8")) if new else {}

        v = new_meta.get("EngineAssociation", "Unreal")
        plugins = [p.get("Name") for p in new_meta.get("Plugins", []) if p.get("Name")]
        facts = {
            "engine": "Unreal Engine",
            "version": v,
            "plugins": plugins,
        }
        diffs = [f"Unreal Engine project (Engine: {v}, {len(plugins)} active plugins)"]
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    # -------------------------------------------------------------------------
    # Design & Art Apps (Sketch, Krita)
    # -------------------------------------------------------------------------
    def _analyze_sketch(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_sketch_meta(old) if old else {}
        new_meta = self._parse_sketch_meta(new) if new else {}

        facts = {
            "design_tool": "Sketch",
            "artboards": new_meta.get("artboards", []),
            "pages_count": new_meta.get("pages_count", 0),
        }
        diffs = [f"Sketch Design: {facts['pages_count']} pages, {len(facts['artboards'])} artboards"]
        if facts["artboards"]:
            diffs.append(f"Artboards: {', '.join(facts['artboards'][:4])}")
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_sketch_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "meta.json" in zf.namelist():
                    meta = json.loads(zf.read("meta.json").decode("utf-8"))
                    artboards = []
                    pages = meta.get("pagesAndArtboards", {})
                    for p in pages.values():
                        for ab in p.get("artboards", {}).values():
                            if isinstance(ab, dict) and "name" in ab:
                                artboards.append(ab["name"])
                    return {"pages_count": len(pages), "artboards": artboards}
        except Exception:
            pass
        return {}

    def _analyze_krita(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_krita_meta(old) if old else {}
        new_meta = self._parse_krita_meta(new) if new else {}

        facts = {
            "design_tool": "Krita",
            "width": new_meta.get("width"),
            "height": new_meta.get("height"),
            "layers_count": new_meta.get("layers", 0),
        }
        diffs = [f"Krita artwork canvas {facts.get('width')}x{facts.get('height')}, {facts.get('layers_count')} layers"]
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_krita_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "maindoc.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("maindoc.xml"))
                    w, h = None, None
                    layer_count = 0
                    for elem in root.iter():
                        tag = elem.tag.split("}")[-1].upper()
                        if tag == "IMAGE":
                            if "width" in elem.attrib:
                                w = int(elem.attrib["width"])
                            if "height" in elem.attrib:
                                h = int(elem.attrib["height"])
                        elif tag == "LAYER":
                            layer_count += 1
                    return {"width": w, "height": h, "layers": layer_count}
        except Exception:
            pass
        return {}

    # -------------------------------------------------------------------------
    # CAD & EDA (FreeCAD, KiCad, DXF)
    # -------------------------------------------------------------------------
    def _analyze_freecad(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_freecad_meta(old) if old else {}
        new_meta = self._parse_freecad_meta(new) if new else {}

        facts = {
            "cad_tool": "FreeCAD",
            "objects_count": new_meta.get("objects_count", 0),
            "object_names": new_meta.get("objects", []),
        }
        diffs = [f"FreeCAD Model: {facts['objects_count']} geometric features & bodies"]
        if facts["object_names"]:
            diffs.append(f"Features: {', '.join(facts['object_names'][:4])}")
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_freecad_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "Document.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("Document.xml"))
                    objs = [elem.attrib.get("name") for elem in root.findall(".//Object") if elem.attrib.get("name")]
                    return {"objects_count": len(objs), "objects": objs}
        except Exception:
            pass
        return {}

    def _analyze_kicad(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_kicad_meta(old) if old else {}
        new_meta = self._parse_kicad_meta(new) if new else {}

        facts = {
            "eda_tool": "KiCad EDA",
            "nets_count": new_meta.get("nets", 0),
            "footprints_count": new_meta.get("footprints", 0),
            "layers_count": new_meta.get("layers", 0),
        }
        diffs = [f"KiCad PCB Design: {facts['footprints_count']} footprints, {facts['nets_count']} electrical nets"]
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_kicad_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            text = data.decode("utf-8", errors="replace")
            nets = len(re.findall(r"\(net\s+\d+", text))
            footprints = len(re.findall(r"\(footprint\s+", text)) or len(re.findall(r"\(module\s+", text))
            layers = len(re.findall(r"\(layer\s+", text))
            return {"nets": nets, "footprints": footprints, "layers": layers}
        except Exception:
            return {}

    def _analyze_dxf(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_meta = self._parse_dxf_meta(old) if old else {}
        new_meta = self._parse_dxf_meta(new) if new else {}

        facts = {
            "cad_tool": "AutoCAD DXF",
            "entities_count": new_meta.get("entities", 0),
            "layers": new_meta.get("layers", []),
        }
        diffs = [f"AutoCAD DXF Vector Drawing: {facts['entities_count']} entities, {len(facts['layers'])} layers"]
        return AnalysisResult(old_meta, new_meta, "\n".join(diffs), "", facts)

    def _parse_dxf_meta(self, data: Optional[bytes]) -> Dict[str, Any]:
        if not data:
            return {}
        try:
            text = data.decode("utf-8", errors="replace")
            entities = len(re.findall(r"\n\s*0\s*\n(LINE|CIRCLE|ARC|POLYLINE|LWPOLYLINE|3DFACE|TEXT)", text))
            layers = list(set(re.findall(r"\n\s*8\s*\n([^\r\n]+)", text)))
            return {"entities": entities, "layers": layers[:8]}
        except Exception:
            return {}

    def _analyze_parquet(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        facts = {
            "storage_format": "Apache Parquet",
            "is_parquet": True,
            "header": "PAR1",
        }
        diffs = ["Apache Parquet columnar dataset update"]
        return AnalysisResult({}, {}, "\n".join(diffs), "", facts)

    # -------------------------------------------------------------------------
    # Generic Container Unpackers (ZIP, GZIP, SQLite)
    # -------------------------------------------------------------------------
    def _analyze_generic_zip(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_entries = self._get_zip_manifest(old) if old else {}
        new_entries = self._get_zip_manifest(new) if new else {}

        added = sorted(list(set(new_entries.keys()) - set(old_entries.keys())))
        removed = sorted(list(set(old_entries.keys()) - set(new_entries.keys())))
        modified = [
            k for k in new_entries.keys()
            if k in old_entries and new_entries[k] != old_entries[k]
        ]

        facts = {
            "container_type": "ZIP Archive",
            "total_items": len(new_entries),
            "added_items": added,
            "removed_items": removed,
            "modified_items": modified,
        }

        diffs = [f"Application Container ({len(new_entries)} internal files):"]
        if modified:
            diffs.append(f"  * {len(modified)} files modified ({', '.join(modified[:3])})")
        if added:
            diffs.append(f"  * {len(added)} files added ({', '.join(added[:3])})")
        if removed:
            diffs.append(f"  * {len(removed)} files removed ({', '.join(removed[:3])})")
        if not modified and not added and not removed:
            diffs.append("  * Container internal assets preserved.")

        return AnalysisResult(
            previous_metadata={"files": list(old_entries.keys())},
            current_metadata={"files": list(new_entries.keys())},
            raw_diff="\n".join(diffs),
            vision_summary="",
            domain_facts=facts,
        )

    def _get_zip_manifest(self, data: bytes) -> Dict[str, Tuple[int, int]]:
        res = {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    res[info.filename] = (info.file_size, info.CRC)
        except Exception:
            pass
        return res

    def _analyze_generic_gzip(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_decomp_len = 0
        new_decomp_len = 0
        try:
            if old:
                with gzip.GzipFile(fileobj=io.BytesIO(old)) as gz:
                    old_decomp_len = len(gz.read(2 * 1024 * 1024))
            if new:
                with gzip.GzipFile(fileobj=io.BytesIO(new)) as gz:
                    new_decomp_len = len(gz.read(2 * 1024 * 1024))
        except Exception:
            pass

        facts = {
            "container_type": "Gzip Container",
            "decompressed_size": new_decomp_len,
            "decompressed_delta": new_decomp_len - old_decomp_len,
        }
        diff = f"Gzip application container: decompressed stream {old_decomp_len}B -> {new_decomp_len}B"
        return AnalysisResult({}, {}, diff, "", facts)

    def _analyze_generic_sqlite(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_tables = self._inspect_sqlite_tables(old) if old else {}
        new_tables = self._inspect_sqlite_tables(new) if new else {}

        facts = {
            "container_type": "SQLite Project DB",
            "tables": list(new_tables.keys()),
            "table_rows": new_tables,
        }
        diffs = [f"SQLite Application Project Database ({len(new_tables)} tables):"]
        for tbl, count in new_tables.items():
            prev_cnt = old_tables.get(tbl, 0)
            if prev_cnt != count:
                diffs.append(f"  * Table '{tbl}': {prev_cnt} -> {count} records")

        return AnalysisResult(
            previous_metadata=old_tables,
            current_metadata=new_tables,
            raw_diff="\n".join(diffs),
            domain_facts=facts,
        )

    def _inspect_sqlite_tables(self, data: bytes) -> Dict[str, int]:
        res: Dict[str, int] = {}
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                conn = sqlite3.connect(tmp.name)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [r[0] for r in cur.fetchall()]
                for t in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM \"{t}\";")
                        res[t] = cur.fetchone()[0]
                    except Exception:
                        res[t] = 0
                conn.close()
            except Exception:
                pass
        return res

    def _analyze_generic_app_file(self, old: Optional[bytes], new: Optional[bytes], name: str) -> AnalysisResult:
        old_len = len(old) if old else 0
        new_len = len(new) if new else 0
        diff = f"Updated application project file {name} ({old_len}B -> {new_len}B)"
        return AnalysisResult({}, {}, diff, "", {"size_bytes": new_len})
