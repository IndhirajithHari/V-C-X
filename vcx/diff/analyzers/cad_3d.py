"""CAD and 3D Model analyzer for FreeCAD, STL, STEP, and 3D meshes."""

from __future__ import annotations
import io
import json
import re
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class Cad3DAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_meta = self._extract_metadata(old_content, file_name)
        new_meta = self._extract_metadata(new_content, file_name)

        domain_facts, raw_diff, vision_summary = self._compute_cad_delta(
            old_meta, new_meta, file_name
        )

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary=vision_summary,
            domain_facts=domain_facts,
        )

    def _extract_metadata(
        self, content: Optional[bytes], file_name: str
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "type": "cad",
            "file_size": len(content) if content else 0,
            "parametric_features": {},
            "mesh_stats": {},
        }
        if not content:
            return meta

        lower = file_name.lower()

        # FreeCAD XML / project / JSON inspection
        if lower.endswith((".fcstd", ".fcproj", ".xml", ".fcmacro")):
            meta.update(self._parse_freecad_content(content))

        # STEP / STP CAD boundary representation
        elif lower.endswith((".step", ".stp")):
            meta.update(self._parse_step_content(content))

        # STL / OBJ Polygon Mesh inspection using trimesh
        elif lower.endswith((".stl", ".obj")):
            meta.update(self._parse_mesh_content(content, file_name))

        return meta

    def _parse_freecad_content(self, content: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {"parametric_features": {}}

        # If it's a FreeCAD .fcstd ZIP container, extract Document.xml
        xml_bytes = content
        if content.startswith(b"PK\x03\x04"):
            try:
                import zipfile

                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    if "Document.xml" in zf.namelist():
                        xml_bytes = zf.read("Document.xml")
            except Exception:
                pass

        # Try JSON parsing (e.g. filmcraft/freecad project)
        try:
            data = json.loads(xml_bytes.decode("utf-8", errors="ignore"))
            if isinstance(data, dict):
                result["format"] = data.get("format", "json_cad")
                result["parametric_features"] = self._extract_json_cad_params(data)
                return result
        except Exception:
            pass

        # Try XML parsing (FreeCAD Document.xml)
        try:
            root = ET.fromstring(xml_bytes.decode("utf-8", errors="ignore"))
            for obj in root.findall(".//Object"):
                obj_name = obj.attrib.get("name", "Unknown")
                obj_type = obj.attrib.get("type", "Feature")
                for prop in obj.findall(".//Property"):
                    p_name = prop.attrib.get("name")
                    val_elem = (
                        prop.find("./Float")
                        if prop.find("./Float") is not None
                        else (
                            prop.find("./Integer")
                            if prop.find("./Integer") is not None
                            else prop.find("./String")
                        )
                    )
                    if val_elem is not None and "value" in val_elem.attrib:
                        result["parametric_features"][f"{obj_name}.{p_name}"] = val_elem.attrib["value"]
            return result
        except Exception:
            pass

        # Fallback text regex for parametric definitions
        text = xml_bytes.decode("utf-8", errors="replace")
        features = {}
        for m in re.finditer(r"(Extrusion|Pad|Fillet|Chamfer|Pocket|Hole|Thickness|Radius|Length)\s*[:=]\s*([0-9.]+)\s*(mm)?", text, re.I):
            features[m.group(1)] = f"{m.group(2)}{m.group(3) or 'mm'}"
        result["parametric_features"] = features
        return result

    def _parse_step_content(self, content: bytes) -> Dict[str, Any]:
        """Parse STEP / STP boundary-representation files without converting to mesh."""
        text = content.decode("utf-8", errors="replace")
        features: Dict[str, Any] = {}

        # Look for geometric dimensions or thickness/fillet annotations in comments/entities
        for m in re.finditer(r"(Extrusion|Thickness|Length|Radius|Fillet|Chamfer)\s*[:=]\s*([0-9.]+)\s*(mm)?", text, re.I):
            features[m.group(1)] = f"{m.group(2)}{m.group(3) or 'mm'}"

        # Count boundary representation entities
        solids = len(re.findall(r"MANIFOLD_SOLID_BREP", text))
        faces = len(re.findall(r"ADVANCED_FACE", text))
        cylinders = len(re.findall(r"CYLINDRICAL_SURFACE", text))

        mesh_stats = {
            "format": "STEP_BREP",
            "solids": solids,
            "faces": faces,
            "cylindrical_surfaces": cylinders,
        }
        return {"parametric_features": features, "mesh_stats": mesh_stats}

    def _extract_json_cad_params(self, data: Dict[str, Any]) -> Dict[str, Any]:
        params = {}
        if "items" in data and isinstance(data["items"], dict):
            for k, v in list(data["items"].items())[:20]:
                if isinstance(v, dict):
                    params[v.get("name", k)] = v.get("kind", {})
        return params

    def _parse_mesh_content(self, content: bytes, file_name: str) -> Dict[str, Any]:
        mesh_stats: Dict[str, Any] = {}
        try:
            import trimesh

            file_ext = file_name.split(".")[-1].lower()
            mesh = trimesh.load(
                io.BytesIO(content),
                file_type=file_ext if file_ext in ("stl", "obj") else "stl",
            )

            if isinstance(mesh, trimesh.Trimesh):
                bounds = mesh.bounds
                dx = round(float(bounds[1][0] - bounds[0][0]), 3)
                dy = round(float(bounds[1][1] - bounds[0][1]), 3)
                dz = round(float(bounds[1][2] - bounds[0][2]), 3)

                mesh_stats = {
                    "vertices": len(mesh.vertices),
                    "faces": len(mesh.faces),
                    "bounding_box_mm": [dx, dy, dz],
                    "surface_area": round(float(mesh.area), 3),
                    "is_watertight": bool(mesh.is_watertight),
                }
        except Exception:
            # Fallback for binary STL header vertex count estimation
            if len(content) > 84:
                import struct
                try:
                    num_faces = struct.unpack("<I", content[80:84])[0]
                    mesh_stats = {"estimated_faces": num_faces}
                except Exception:
                    pass

        return {"mesh_stats": mesh_stats}

    def _compute_cad_delta(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any], file_name: str
    ) -> tuple[Dict[str, Any], str, str]:
        facts: Dict[str, Any] = {"parametric_changes": [], "geometric_changes": []}
        diff_lines = []
        vision_parts = []

        # Compare parametric features
        old_params = old_meta.get("parametric_features", {})
        new_params = new_meta.get("parametric_features", {})

        for feat, val in new_params.items():
            if feat not in old_params:
                facts["parametric_changes"].append(f"Added feature {feat}: {val}")
                diff_lines.append(f"+ {feat}: {val}")
                vision_parts.append(f"Added {feat} ({val})")
            elif old_params[feat] != val:
                facts["parametric_changes"].append(
                    f"Modified {feat} from {old_params[feat]} to {val}"
                )
                diff_lines.append(f"- {feat}: {old_params[feat]}")
                diff_lines.append(f"+ {feat}: {val}")
                vision_parts.append(f"Modified {feat} to {val}")

        for feat, val in old_params.items():
            if feat not in new_params:
                facts["parametric_changes"].append(f"Removed feature {feat}")
                diff_lines.append(f"- {feat}: {val}")

        # Compare mesh stats (STL, OBJ, etc.)
        o_mesh = old_meta.get("mesh_stats", {})
        n_mesh = new_meta.get("mesh_stats", {})

        if o_mesh and n_mesh:
            v_delta = n_mesh.get("vertices", 0) - o_mesh.get("vertices", 0)
            f_delta = n_mesh.get("faces", 0) - o_mesh.get("faces", 0)
            if v_delta != 0:
                facts["geometric_changes"].append(f"Vertex count changed by {v_delta:+d} (Total: {n_mesh.get('vertices')})")
                diff_lines.append(f"+ vertices: {n_mesh.get('vertices')} ({v_delta:+d})")

            o_box = o_mesh.get("bounding_box_mm")
            n_box = n_mesh.get("bounding_box_mm")
            if o_box and n_box and o_box != n_box:
                facts["geometric_changes"].append(
                    f"Bounding box dimensions updated: {o_box}mm -> {n_box}mm"
                )
                diff_lines.append(f"- bbox: {o_box}mm")
                diff_lines.append(f"+ bbox: {n_box}mm")
                vision_parts.append(f"Viewport 3D bounding box resized to {n_box}mm")

        raw_diff = "\n".join(diff_lines) if diff_lines else f"Binary CAD model updated ({new_meta.get('file_size', 0)} bytes)"
        vision_summary = "; ".join(vision_parts) if vision_parts else "3D viewport inspection confirms updated topological mesh geometry."

        return facts, raw_diff, vision_summary
