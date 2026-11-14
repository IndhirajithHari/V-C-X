"""Native FreeCAD (.FCStd) Semantic Adapter for VCX.

Opens .FCStd files in memory as ZIP archives, parses Document.xml and GuiDocument.xml,
and performs 3-way/2-way parametric property diffs (objects added/removed, dimensions,
placements, fillets, extrusion lengths, sketch constraints).
Allows the Semantic Differ Agent to write exact CAD commit messages without a vision model.
"""

from __future__ import annotations
import io
import json
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET
import zipfile


class FreeCADAdapter:
    """Extracts parametric CAD topology and property deltas from .FCStd archives."""

    @staticmethod
    def _extract_xml_contents(data: bytes) -> Tuple[Optional[str], Optional[str]]:
        """Extract Document.xml and GuiDocument.xml from in-memory bytes or zip."""
        if not data:
            return None, None

        # Check if zip container (PK magic bytes)
        if data.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    doc_xml = None
                    gui_xml = None
                    for name in zf.namelist():
                        if name.endswith("Document.xml") and not name.endswith("GuiDocument.xml"):
                            doc_xml = zf.read(name).decode("utf-8", errors="replace")
                        elif name.endswith("GuiDocument.xml"):
                            gui_xml = zf.read(name).decode("utf-8", errors="replace")
                    return doc_xml, gui_xml
            except Exception:
                pass

        # Raw XML text fallback
        text = data.decode("utf-8", errors="replace")
        if "<Document" in text:
            return text, None
        return None, None

    @classmethod
    def parse_document_xml(cls, xml_str: str) -> Dict[str, Any]:
        """Parse FreeCAD Document.xml into a structured dictionary of objects and properties."""
        if not xml_str:
            return {"objects": {}, "sketch_constraints": {}}

        try:
            root = ET.fromstring(xml_str)
        except Exception:
            return {"objects": {}, "sketch_constraints": {}}

        objects: Dict[str, Dict[str, Any]] = {}
        sketch_constraints: Dict[str, List[Dict[str, str]]] = {}

        # Scan all <Object name="..." type="...">
        for obj in root.findall(".//Object"):
            oname = obj.attrib.get("name", "Unknown")
            otype = obj.attrib.get("type", "Unknown")
            props: Dict[str, str] = {}

            # Parse each <Property name="..." type="...">
            for prop in obj.findall(".//Property"):
                pname = prop.attrib.get("name")
                if not pname:
                    continue

                # Check known value element tags: Float, Integer, String, Bool, Vector, Placement
                val_str = None
                for val_tag in ("Float", "Integer", "String", "Bool"):
                    c = prop.find(val_tag)
                    if c is not None and "value" in c.attrib:
                        val_str = c.attrib["value"]
                        break

                if val_str is None:
                    # Check placement or vector
                    pos = prop.find(".//PropertyVector")
                    if pos is not None and "value" in pos.attrib:
                        val_str = f"Vector({pos.attrib['value']})"
                    else:
                        sub = prop.find(".//*[@value]")
                        if sub is not None:
                            val_str = sub.attrib["value"]

                if val_str is not None:
                    props[pname] = val_str

            objects[oname] = {
                "type": otype,
                "properties": props,
            }

            # Check sketch constraints if this is a Sketch object
            if "Sketch" in otype or "Sketcher" in otype or oname.lower().startswith("sketch"):
                constraints = []
                for c in obj.findall(".//Constraint"):
                    c_dict = {
                        "name": c.attrib.get("Name", ""),
                        "type": c.attrib.get("Type", ""),
                        "value": c.attrib.get("Value", ""),
                    }
                    constraints.append(c_dict)
                if constraints:
                    sketch_constraints[oname] = constraints

        return {
            "objects": objects,
            "sketch_constraints": sketch_constraints,
        }

    @classmethod
    def diff(
        cls,
        base_data: Optional[bytes],
        current_data: bytes,
        file_name: str = "model.fcstd",
    ) -> Dict[str, Any]:
        """Perform exact parametric comparison between two FreeCAD states."""
        base_doc_xml, _ = cls._extract_xml_contents(base_data) if base_data else (None, None)
        curr_doc_xml, _ = cls._extract_xml_contents(current_data)

        base_parsed = cls.parse_document_xml(base_doc_xml) if base_doc_xml else {"objects": {}, "sketch_constraints": {}}
        curr_parsed = cls.parse_document_xml(curr_doc_xml) if curr_doc_xml else {"objects": {}, "sketch_constraints": {}}

        base_objs = base_parsed.get("objects", {})
        curr_objs = curr_parsed.get("objects", {})

        objects_added: List[Dict[str, str]] = []
        objects_removed: List[Dict[str, str]] = []
        properties_modified: List[Dict[str, Any]] = []

        all_names = set(base_objs.keys()) | set(curr_objs.keys())

        for name in sorted(all_names):
            if name not in base_objs:
                objects_added.append({
                    "name": name,
                    "type": curr_objs[name].get("type", "Unknown"),
                })
            elif name not in curr_objs:
                objects_removed.append({
                    "name": name,
                    "type": base_objs[name].get("type", "Unknown"),
                })
            else:
                # Compare properties
                b_props = base_objs[name].get("properties", {})
                c_props = curr_objs[name].get("properties", {})
                for p_key in sorted(set(b_props.keys()) | set(c_props.keys())):
                    b_val = b_props.get(p_key)
                    c_val = c_props.get(p_key)
                    if b_val != c_val:
                        properties_modified.append({
                            "object": name,
                            "property": p_key,
                            "old_value": b_val,
                            "new_value": c_val,
                        })

        # Compare sketch constraints
        base_sk = base_parsed.get("sketch_constraints", {})
        curr_sk = curr_parsed.get("sketch_constraints", {})
        sketch_changes: List[str] = []

        for sk_name in sorted(set(base_sk.keys()) | set(curr_sk.keys())):
            b_c = base_sk.get(sk_name, [])
            c_c = curr_sk.get(sk_name, [])
            if b_c != c_c:
                sketch_changes.append(f"Constraints modified in {sk_name} ({len(b_c)} -> {len(c_c)})")

        # Synthesize technical bullet points
        bullets: List[str] = []
        for a in objects_added:
            bullets.append(f"Added CAD feature: {a['name']} [{a['type']}]")
        for r in objects_removed:
            bullets.append(f"Removed CAD feature: {r['name']}")
        for m in properties_modified:
            bullets.append(f"Modified {m['object']}.{m['property']}: {m['old_value']} -> {m['new_value']}")
        for sc in sketch_changes:
            bullets.append(sc)

        has_changes = bool(objects_added or objects_removed or properties_modified or sketch_changes)

        summary = (
            f"Parametric changes in {file_name}: "
            + f"+{len(objects_added)} features, -{len(objects_removed)} features, {len(properties_modified)} dimensions updated"
            if has_changes
            else f"No parametric changes in {file_name}"
        )

        return {
            "format": "FreeCAD",
            "file": file_name,
            "has_changes": has_changes,
            "objects_added": objects_added,
            "objects_removed": objects_removed,
            "properties_modified": properties_modified,
            "sketch_changes": sketch_changes,
            "technical_bullets": bullets,
            "summary": summary,
        }
