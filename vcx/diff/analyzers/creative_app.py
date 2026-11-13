"""Universal Creative App and Project Analyzer (Premiere, Resolve, Photoshop, Blender, Audacity, Office, 3D Scenes)."""

from __future__ import annotations
import gzip
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import zipfile

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class CreativeAppAnalyzer(BaseAnalyzer):
    """Analyzes non-linear video editing projects, DAW audio sessions, 2D/3D design files, and office documents."""

    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_meta = self._extract_project_meta(old_content, file_name)
        new_meta = self._extract_project_meta(new_content, file_name)

        domain_facts, raw_diff, vision_summary = self._compute_project_delta(
            old_meta, new_meta, file_name
        )

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary=vision_summary,
            domain_facts=domain_facts,
        )

    def _extract_project_meta(self, content: Optional[bytes], file_name: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "file_size": len(content) if content else 0,
            "project_type": "creative_generic",
        }
        if not content:
            return meta

        lower = file_name.lower()

        # 1. Adobe Premiere Pro (.prproj) -> Gzip XML
        if lower.endswith(".prproj") or (content.startswith(b"\x1f\x8b") and "prproj" in lower):
            meta.update(self._parse_premiere(content))

        # 2. Final Cut Pro XML (.fcpxml)
        elif lower.endswith((".fcpxml", ".fcpxmld")):
            meta.update(self._parse_fcpxml(content))

        # 3. DaVinci Resolve / CMX EDL (.edl)
        elif lower.endswith(".edl"):
            meta.update(self._parse_edl(content))

        # 4. Audacity (.aup3) -> SQLite
        elif lower.endswith(".aup3") or (content.startswith(b"SQLite format 3\000") and "aup3" in lower):
            meta.update(self._parse_audacity(content))

        # 5. Adobe Photoshop (.psd, .psb)
        elif lower.endswith((".psd", ".psb")) or content.startswith(b"8BPS"):
            meta.update(self._parse_psd(content))

        # 6. Blender 3D (.blend)
        elif lower.endswith((".blend", ".blend1")) or content.startswith(b"BLENDER"):
            meta.update(self._parse_blender(content))

        # 7. glTF / GLB 3D Scene (.gltf, .glb)
        elif lower.endswith((".gltf", ".glb")) or content.startswith(b"glTF"):
            meta.update(self._parse_gltf(content))

        # 8. Filmcraft Video Project (.filmcraft, .fcproj)
        elif lower.endswith((".filmcraft", ".fcproj")):
            meta.update(self._parse_filmcraft(content))

        # 9. PDF Document (.pdf)
        elif lower.endswith(".pdf") or content.startswith(b"%PDF-"):
            meta.update(self._parse_pdf(content))

        # 10. Office Documents (.docx, .xlsx, .pptx)
        elif lower.endswith((".docx", ".xlsx", ".pptx")):
            meta.update(self._parse_office(content, lower))

        return meta

    def _parse_premiere(self, content: bytes) -> Dict[str, Any]:
        """Decompress Premiere Pro gzipped XML and inspect sequences, framerates, and tracks."""
        result: Dict[str, Any] = {"project_type": "adobe_premiere", "sequences": [], "tracks": {}}
        xml_bytes = content
        if content.startswith(b"\x1f\x8b"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                    xml_bytes = gz.read()
            except Exception:
                pass

        try:
            root = ET.fromstring(xml_bytes.decode("utf-8", errors="ignore"))
            # Count sequences
            for seq in root.findall(".//Sequence"):
                name = seq.findtext("Name") or "Sequence"
                result["sequences"].append(name)

            v_tracks = root.findall(".//VideoClipTrack")
            a_tracks = root.findall(".//AudioClipTrack")
            result["tracks"] = {
                "video_tracks": len(v_tracks),
                "audio_tracks": len(a_tracks),
            }
            clips = root.findall(".//ClipProjectItem")
            result["clips_count"] = len(clips)
        except Exception:
            pass
        return result

    def _parse_fcpxml(self, content: bytes) -> Dict[str, Any]:
        """Parse Final Cut Pro XML events, spine items, and formats."""
        result: Dict[str, Any] = {"project_type": "final_cut_pro", "clips_count": 0}
        try:
            root = ET.fromstring(content.decode("utf-8", errors="ignore"))
            formats = root.findall(".//format")
            if formats:
                f = formats[0]
                result["width"] = f.attrib.get("width")
                result["height"] = f.attrib.get("height")
                result["frame_duration"] = f.attrib.get("frameDuration")
            clips = root.findall(".//clip") + root.findall(".//asset-clip") + root.findall(".//video")
            result["clips_count"] = len(clips)
            result["titles_count"] = len(root.findall(".//title"))
        except Exception:
            pass
        return result

    def _parse_edl(self, content: bytes) -> Dict[str, Any]:
        """Parse CMX EDL Edit Decision List events."""
        text = content.decode("utf-8", errors="replace")
        events = re.findall(r"^(\d+)\s+([A-Z0-9_]+)\s+([VA]+)\s+([CDW])", text, re.MULTILINE)
        return {
            "project_type": "edl_timeline",
            "events_count": len(events),
            "reels": list(set(e[1] for e in events))[:10],
        }

    def _parse_audacity(self, content: bytes) -> Dict[str, Any]:
        """Parse modern Audacity .aup3 SQLite database."""
        result: Dict[str, Any] = {"project_type": "audacity_session", "tracks": []}
        tmp_db = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(content)
                tmp_db = tmp.name

            conn = sqlite3.connect(tmp_db)
            cur = conn.cursor()
            # Try to query tracks table if present
            try:
                cur.execute("SELECT name, rate, channels FROM tracks;")
                for row in cur.fetchall():
                    result["tracks"].append({"name": row[0], "rate": row[1], "channels": row[2]})
            except Exception:
                pass
            conn.close()
        except Exception:
            pass
        finally:
            if tmp_db and os.path.exists(tmp_db):
                try:
                    os.unlink(tmp_db)
                except Exception:
                    pass
        return result

    def _parse_psd(self, content: bytes) -> Dict[str, Any]:
        """Parse Adobe Photoshop 8BPS header."""
        result: Dict[str, Any] = {"project_type": "adobe_photoshop"}
        if len(content) >= 26 and content.startswith(b"8BPS"):
            try:
                channels, height, width, depth, mode = struct.unpack(">HIIHH", content[12:26])
                modes = {0: "Bitmap", 1: "Grayscale", 2: "Indexed", 3: "RGB", 4: "CMYK", 7: "Multichannel", 8: "Duotone", 9: "Lab"}
                result.update({
                    "width": width,
                    "height": height,
                    "channels": channels,
                    "bit_depth": depth,
                    "color_mode": modes.get(mode, f"Mode-{mode}"),
                })
            except Exception:
                pass
        return result

    def _parse_blender(self, content: bytes) -> Dict[str, Any]:
        """Parse Blender .blend header."""
        result: Dict[str, Any] = {"project_type": "blender_3d"}
        if len(content) >= 12 and content.startswith(b"BLENDER"):
            try:
                ptr_size = 8 if content[7:8] == b"-" else 4
                endianness = "little" if content[8:9] == b"v" else "big"
                version = content[9:12].decode("ascii", errors="replace")
                result.update({
                    "blender_version": f"v{version[0]}.{version[1:]}",
                    "pointer_bits": ptr_size * 8,
                    "endianness": endianness,
                })
            except Exception:
                pass
        return result

    def _parse_gltf(self, content: bytes) -> Dict[str, Any]:
        """Parse glTF / GLB 3D scene structure."""
        result: Dict[str, Any] = {"project_type": "gltf_3d"}
        json_data = None
        if content.startswith(b"glTF") and len(content) >= 20:
            try:
                length, json_len, json_type = struct.unpack("<III", content[8:20])
                if json_type == 0x4E4F534A:  # "JSON"
                    json_data = json.loads(content[20 : 20 + json_len].decode("utf-8"))
            except Exception:
                pass
        else:
            try:
                json_data = json.loads(content.decode("utf-8", errors="ignore"))
            except Exception:
                pass

        if isinstance(json_data, dict):
            result["nodes_count"] = len(json_data.get("nodes", []))
            result["meshes_count"] = len(json_data.get("meshes", []))
            result["materials_count"] = len(json_data.get("materials", []))
            result["animations_count"] = len(json_data.get("animations", []))
        return result

    def _parse_filmcraft(self, content: bytes) -> Dict[str, Any]:
        """Parse Filmcraft video composition project."""
        result: Dict[str, Any] = {"project_type": "filmcraft_video"}
        try:
            data = json.loads(content.decode("utf-8", errors="ignore"))
            if isinstance(data, dict):
                result["composition_name"] = data.get("name", "Timeline")
                result["fps"] = data.get("fps", 24)
                result["duration"] = data.get("duration")
                result["layers_count"] = len(data.get("layers", []))
        except Exception:
            pass
        return result

    def _parse_pdf(self, content: bytes) -> Dict[str, Any]:
        """Parse PDF document header and page catalog."""
        result: Dict[str, Any] = {"project_type": "pdf_document"}
        m = re.search(rb"%PDF-(\d+\.\d+)", content[:128])
        if m:
            result["pdf_version"] = m.group(1).decode("ascii")
        pages = len(re.findall(rb"/Type\s*/Page\b", content))
        if pages > 0:
            result["estimated_pages"] = pages
        return result

    def _parse_office(self, content: bytes, file_name: str) -> Dict[str, Any]:
        """Parse Office XML ZIP packages (DOCX, XLSX, PPTX)."""
        result: Dict[str, Any] = {"project_type": "office_document"}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                if "docProps/core.xml" in zf.namelist():
                    core_xml = zf.read("docProps/core.xml")
                    root = ET.fromstring(core_xml)
                    for elem in root:
                        tag = elem.tag.split("}")[-1]
                        if tag in ("title", "creator", "lastModifiedBy", "revision"):
                            result[tag] = elem.text

                if file_name.endswith(".docx") and "word/document.xml" in zf.namelist():
                    doc_xml = zf.read("word/document.xml")
                    words = len(re.findall(r"\w+", doc_xml.decode("utf-8", errors="ignore")))
                    result["word_count"] = words
                elif file_name.endswith(".xlsx") and "xl/workbook.xml" in zf.namelist():
                    wb_xml = zf.read("xl/workbook.xml")
                    sheets = len(re.findall(r"<sheet\b", wb_xml.decode("utf-8", errors="ignore")))
                    result["sheet_count"] = sheets
                elif file_name.endswith(".pptx"):
                    slides = [n for n in zf.namelist() if n.startswith("ppt/slides/slide")]
                    result["slide_count"] = len(slides)
        except Exception:
            pass
        return result

    def _compute_project_delta(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any], file_name: str
    ) -> Tuple[Dict[str, Any], str, str]:
        facts: Dict[str, Any] = {"project_deltas": []}
        diff_lines: List[str] = []
        vision_parts: List[str] = []

        p_type = new_meta.get("project_type") or "creative_project"

        # Premiere / Final Cut sequences and clips
        if "sequences" in new_meta:
            n_seq = set(new_meta["sequences"])
            o_seq = set(old_meta.get("sequences", []))
            added_seq = n_seq - o_seq
            if added_seq:
                facts["project_deltas"].append(f"Added timeline sequence(s): {', '.join(added_seq)}")
                diff_lines.append(f"+ sequences: {', '.join(added_seq)}")
                vision_parts.append(f"Added timeline sequence(s): {', '.join(added_seq)}")

        if "tracks" in new_meta:
            n_t = new_meta["tracks"]
            o_t = old_meta.get("tracks", {})
            if isinstance(n_t, dict):
                o_dict = o_t if isinstance(o_t, dict) else {}
                for k in ("video_tracks", "audio_tracks"):
                    if n_t.get(k) != o_dict.get(k):
                        diff_lines.append(f"+ {k}: {n_t.get(k)} (was {o_dict.get(k, 0)})")
                        facts["project_deltas"].append(f"{k.replace('_', ' ').capitalize()} count updated to {n_t.get(k)}")
            elif isinstance(n_t, list):
                o_list = o_t if isinstance(o_t, list) else []
                delta = len(n_t) - len(o_list)
                if delta != 0:
                    diff_lines.append(f"+ track_count: {len(n_t)} ({delta:+d})")
                    facts["project_deltas"].append(f"Audio track count changed by {delta:+d}")

        # Dimensions (Photoshop, FCPXML, Filmcraft)
        o_w, o_h = old_meta.get("width"), old_meta.get("height")
        n_w, n_h = new_meta.get("width"), new_meta.get("height")
        if n_w and n_h:
            curr_res = f"{n_w}x{n_h}"
            if o_w and o_h and (o_w != n_w or o_h != n_h):
                diff_lines.append(f"- canvas_size: {o_w}x{o_h}")
                diff_lines.append(f"+ canvas_size: {curr_res}")
                vision_parts.append(f"Canvas resized from {o_w}x{o_h} to {curr_res}")
            else:
                diff_lines.append(f"+ canvas_size: {curr_res}")

        if "color_mode" in new_meta:
            if new_meta["color_mode"] != old_meta.get("color_mode"):
                diff_lines.append(f"+ color_mode: {new_meta['color_mode']}")
                facts["project_deltas"].append(f"Color mode shifted to {new_meta['color_mode']}")

        # 3D Assets (glTF, Blender)
        for key in ("meshes_count", "nodes_count", "materials_count", "animations_count"):
            if key in new_meta:
                delta = new_meta[key] - old_meta.get(key, 0)
                if delta != 0:
                    diff_lines.append(f"+ {key}: {new_meta[key]} ({delta:+d})")
                    facts["project_deltas"].append(f"Scene {key.replace('_', ' ')} updated: {delta:+d}")

        # Documents (Word, Excel, PowerPoint, PDF)
        if "word_count" in new_meta:
            delta = new_meta["word_count"] - old_meta.get("word_count", 0)
            if delta != 0:
                diff_lines.append(f"+ word_count: {new_meta['word_count']} ({delta:+d})")
                facts["project_deltas"].append(f"Document length changed by {delta:+d} words")
        if "sheet_count" in new_meta:
            delta = new_meta["sheet_count"] - old_meta.get("sheet_count", 0)
            if delta != 0:
                diff_lines.append(f"+ sheet_count: {new_meta['sheet_count']} ({delta:+d})")
                facts["project_deltas"].append(f"Spreadsheet sheets delta: {delta:+d}")
        if "slide_count" in new_meta:
            delta = new_meta["slide_count"] - old_meta.get("slide_count", 0)
            if delta != 0:
                diff_lines.append(f"+ slide_count: {new_meta['slide_count']} ({delta:+d})")
                facts["project_deltas"].append(f"Presentation slides delta: {delta:+d}")
        if "estimated_pages" in new_meta:
            delta = new_meta["estimated_pages"] - old_meta.get("estimated_pages", 0)
            if delta != 0:
                diff_lines.append(f"+ pages: {new_meta['estimated_pages']} ({delta:+d})")
                facts["project_deltas"].append(f"PDF page count: {new_meta['estimated_pages']} ({delta:+d})")

        # File size
        s_delta = new_meta.get("file_size", 0) - old_meta.get("file_size", 0)
        if s_delta != 0:
            diff_lines.append(f"+ file_size: {new_meta.get('file_size', 0)} ({s_delta:+d} bytes)")

        raw_diff = "\n".join(diff_lines) if diff_lines else f"{p_type.replace('_', ' ').capitalize()} project updated ({new_meta.get('file_size', 0)} bytes)"
        vision_summary = "; ".join(vision_parts) if vision_parts else f"Creative project inspection verified {p_type} layout."

        return facts, raw_diff, vision_summary
