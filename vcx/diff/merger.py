"""Multi-Domain 3-Way Semantic Merge Engine for VCX.

Provides domain-aware conflict resolution for Verilog/EDA RTL, CAD parametric models,
Python AST symbols, SQLite/CSV databases, and source code.
"""

from __future__ import annotations
import ast
import csv
import difflib
import io
import json
import re
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET

from vcx.core.types import MergeConflict, MergeResult


class SemanticMerger:
    def merge(
        self,
        base_bytes: Optional[bytes],
        ours_bytes: bytes,
        theirs_bytes: bytes,
        file_name: str,
        file_type: str,
    ) -> Tuple[bool, bytes, List[str], Optional[MergeConflict]]:
        """Perform 3-way semantic merge across base, ours, and theirs.

        Returns (success, merged_bytes, semantic_explanations, conflict_if_any).
        """
        # If identical changes on both branches, trivial merge
        if ours_bytes == theirs_bytes:
            return True, ours_bytes, ["Both branches made identical modifications"], None

        # If base is missing, resolve two new files
        base = base_bytes or b""

        # 1. Hardware / EDA
        if file_type.startswith("eda/"):
            return self._merge_eda(base, ours_bytes, theirs_bytes, file_name)

        # 2. CAD / 3D Parametric Models
        if file_type.startswith("cad/"):
            return self._merge_cad(base, ours_bytes, theirs_bytes, file_name)

        # 3. Databases and Logs
        if file_type.startswith("database/") or file_type.startswith("log/"):
            return self._merge_database(base, ours_bytes, theirs_bytes, file_name, file_type)

        # 4. Source Code (Python AST & Generic)
        if file_type.startswith("source/") or file_type == "text/plain":
            return self._merge_source(base, ours_bytes, theirs_bytes, file_name)

        # 5. Binary Fallback
        return False, ours_bytes, [], MergeConflict(
            path=file_name,
            domain="binary",
            description=f"Binary file {file_name} modified incompatibly on both branches.",
        )

    # --- HARDWARE / EDA MERGE ---

    def _merge_eda(
        self, base: bytes, ours: bytes, theirs: bytes, file_name: str
    ) -> Tuple[bool, bytes, List[str], Optional[MergeConflict]]:
        ours_text = ours.decode("utf-8", errors="replace")
        theirs_text = theirs.decode("utf-8", errors="replace")
        base_text = base.decode("utf-8", errors="replace")

        # Floorplan JSON merge
        if file_name.endswith((".json", ".def", ".lef")) or "floorplan" in file_name.lower():
            try:
                b_json = json.loads(base_text) if base_text.strip() else {}
                o_json = json.loads(ours_text)
                t_json = json.loads(theirs_text)

                merged_macros = dict(b_json.get("macros", {}))
                o_macros = o_json.get("macros", {})
                t_macros = t_json.get("macros", {})

                explanations = []
                for k, v in o_macros.items():
                    if b_json.get("macros", {}).get(k) != v:
                        merged_macros[k] = v
                        explanations.append(f"Applied macro placement update for '{k}' from ours")

                for k, v in t_macros.items():
                    if b_json.get("macros", {}).get(k) != v:
                        if k in o_macros and o_macros[k] != v and b_json.get("macros", {}).get(k) != o_macros[k]:
                            return False, ours, [], MergeConflict(
                                path=file_name,
                                domain="eda-floorplan",
                                description=f"Conflicting coordinate placements for macro '{k}'",
                            )
                        merged_macros[k] = v
                        explanations.append(f"Applied macro placement update for '{k}' from theirs")

                merged_doc = dict(o_json)
                merged_doc["macros"] = merged_macros
                return True, json.dumps(merged_doc, indent=2).encode("utf-8"), explanations, None
            except Exception:
                pass

        # Verilog / SystemVerilog Semantic Port & Logic Merge
        def extract_ports(text: str) -> List[str]:
            m = re.search(r"module\s+[a-zA-Z0-9_]+\s*(?:#\s*\([^)]*\))?\s*\((.*?)\);", text, re.DOTALL)
            if not m:
                return []
            ports = []
            for p in m.group(1).split(","):
                clean = " ".join(p.split()).strip()
                if clean:
                    ports.append(clean)
            return ports

        base_ports = extract_ports(base_text)
        ours_ports = extract_ports(ours_text)
        theirs_ports = extract_ports(theirs_text)

        new_ours_ports = [p for p in ours_ports if p not in base_ports]
        new_theirs_ports = [p for p in theirs_ports if p not in base_ports]

        def get_body(text: str) -> str:
            m = re.search(r"\((.*?)\);(.*?)endmodule", text, re.DOTALL)
            return m.group(2).strip() if m else ""

        body_base = get_body(base_text)
        body_ours = get_body(ours_text)
        body_theirs = get_body(theirs_text)

        merged_body, body_conflict = self._line_3way_merge(body_base, body_ours, body_theirs, file_name)

        if not body_conflict and (new_ours_ports or new_theirs_ports):
            combined_ports = list(base_ports)
            for p in new_ours_ports:
                if p not in combined_ports:
                    combined_ports.append(p)
            for p in new_theirs_ports:
                if p not in combined_ports:
                    combined_ports.append(p)

            mod_match = re.search(r"module\s+([a-zA-Z0-9_]+)", ours_text)
            mod_name = mod_match.group(1) if mod_match else "module"
            ports_formatted = ",\n    ".join(combined_ports)
            merged_verilog = f"module {mod_name} (\n    {ports_formatted}\n);\n    {merged_body}\nendmodule\n"
            explanations = [
                f"Merged hardware ports: ours ({', '.join(new_ours_ports)}) and theirs ({', '.join(new_theirs_ports)})"
            ]
            return True, merged_verilog.encode("utf-8"), explanations, None

        # Standard line-level 3-way merge
        merged_lines, conflict = self._line_3way_merge(base_text, ours_text, theirs_text, file_name)
        if not conflict:
            explanations = ["Synthesized non-overlapping Verilog RTL control paths"]
            return True, merged_lines.encode("utf-8"), explanations, None

        return False, ours, [], conflict

    # --- CAD / 3D PARAMETRIC MERGE ---

    def _merge_cad(
        self, base: bytes, ours: bytes, theirs: bytes, file_name: str
    ) -> Tuple[bool, bytes, List[str], Optional[MergeConflict]]:
        # FreeCAD XML / Document.xml parametric merge
        if file_name.endswith((".fcstd", ".xml", ".fcproj")):
            try:
                base_root = ET.fromstring(base.decode("utf-8", errors="ignore")) if base.strip() else None
                ours_root = ET.fromstring(ours.decode("utf-8", errors="ignore"))
                theirs_root = ET.fromstring(theirs.decode("utf-8", errors="ignore"))

                # Property maps: (obj_name, prop_name) -> (property_element, value_str)
                def get_props(root):
                    props = {}
                    if root is None:
                        return props
                    for obj in root.findall(".//Object"):
                        oname = obj.attrib.get("name", "Unknown")
                        for p in obj.findall(".//Property"):
                            pname = p.attrib.get("name")
                            val_elem = None
                            for tag in ("Float", "Integer", "String"):
                                c = p.find(tag)
                                if c is not None and "value" in c.attrib:
                                    val_elem = c
                                    break
                            if val_elem is not None:
                                props[(oname, pname)] = (p, val_elem.attrib["value"])
                    return props

                b_props = get_props(base_root)
                o_props = get_props(ours_root)
                t_props = get_props(theirs_root)

                explanations = []
                # Check for changes in ours and theirs
                for k, (p_elem, val) in t_props.items():
                    b_val = b_props.get(k, (None, None))[1]
                    o_val = o_props.get(k, (None, None))[1]

                    if val != b_val:
                        # theirs changed this property
                        if o_val != b_val and o_val != val:
                            # Both changed the same property to different values -> conflict!
                            return False, ours, [], MergeConflict(
                                path=file_name,
                                domain="cad-parametric",
                                description=f"Conflicting dimension for {k[0]}.{k[1]}: ours={o_val}, theirs={val}",
                            )
                        # Non-conflicting addition or modification from theirs: inject into ours
                        if k in o_props:
                            # Update existing property element in ours_root
                            target_elem = None
                            for tag in ("Float", "Integer", "String"):
                                c = o_props[k][0].find(tag)
                                if c is not None:
                                    target_elem = c
                                    break
                            if target_elem is not None:
                                target_elem.attrib["value"] = val
                        else:
                            # Append new property to matching Object in ours_root
                            for obj in ours_root.findall(".//Object"):
                                if obj.attrib.get("name") == k[0]:
                                    obj.append(p_elem)
                                    break
                        explanations.append(f"Merged parametric update: {k[0]}.{k[1]} = {val}")

                merged_xml = ET.tostring(ours_root, encoding="utf-8")
                return True, merged_xml, explanations or ["Merged independent CAD parametric parameters"], None
            except Exception:
                pass

        # Text-based STEP file / regex parametric merge
        ours_text = ours.decode("utf-8", errors="replace")
        theirs_text = theirs.decode("utf-8", errors="replace")
        base_text = base.decode("utf-8", errors="replace")

        merged_text, conflict = self._line_3way_merge(base_text, ours_text, theirs_text, file_name)
        if not conflict:
            return True, merged_text.encode("utf-8"), ["Merged non-conflicting CAD geometric features"], None

        return False, ours, [], conflict

    # --- SOURCE CODE MERGE ---

    def _merge_source(
        self, base: bytes, ours: bytes, theirs: bytes, file_name: str
    ) -> Tuple[bool, bytes, List[str], Optional[MergeConflict]]:
        ours_text = ours.decode("utf-8", errors="replace")
        theirs_text = theirs.decode("utf-8", errors="replace")
        base_text = base.decode("utf-8", errors="replace")

        # Python AST symbol merge
        if file_name.endswith(".py"):
            try:
                base_tree = ast.parse(base_text) if base_text.strip() else None
                ours_tree = ast.parse(ours_text)
                theirs_tree = ast.parse(theirs_text)

                def get_fn_names(tree):
                    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if tree else {}

                b_fns = get_fn_names(base_tree)
                o_fns = get_fn_names(ours_tree)
                t_fns = get_fn_names(theirs_tree)

                new_o = set(o_fns.keys()) - set(b_fns.keys())
                new_t = set(t_fns.keys()) - set(b_fns.keys())

                # If non-overlapping function additions
                if new_o and new_t and not (new_o & new_t):
                    # Combine their functions into ours
                    extra_code = "\n\n" + "\n\n".join(ast.unparse(t_fns[f]) for f in sorted(list(new_t)))
                    merged_py = (ours_text.rstrip() + extra_code + "\n").encode("utf-8")
                    return True, merged_py, [f"Semantically merged new functions from theirs: {', '.join(sorted(list(new_t)))}"], None
            except Exception:
                pass

        # General 3-way line merge
        merged_text, conflict = self._line_3way_merge(base_text, ours_text, theirs_text, file_name)
        if not conflict:
            return True, merged_text.encode("utf-8"), ["Merged non-conflicting code changes"], None

        return False, ours, [], conflict

    # --- DATABASE & LOGS MERGE ---

    def _merge_database(
        self, base: bytes, ours: bytes, theirs: bytes, file_name: str, file_type: str
    ) -> Tuple[bool, bytes, List[str], Optional[MergeConflict]]:
        # CSV / Log Append Merge
        if file_name.endswith((".csv", ".tsv", ".log", ".jsonl")):
            o_lines = ours.decode("utf-8", errors="replace").splitlines()
            t_lines = theirs.decode("utf-8", errors="replace").splitlines()
            b_lines = base.decode("utf-8", errors="replace").splitlines()

            # Find appended lines
            new_in_ours = o_lines[len(b_lines) :] if len(o_lines) >= len(b_lines) else []
            new_in_theirs = t_lines[len(b_lines) :] if len(t_lines) >= len(b_lines) else []

            # Combine distinct appended entries
            combined = list(b_lines)
            combined.extend(new_in_ours)
            for line in new_in_theirs:
                if line not in combined:
                    combined.append(line)

            merged_data = ("\n".join(combined) + "\n").encode("utf-8")
            return (
                True,
                merged_data,
                [f"Appended {len(new_in_ours)} records from ours and {len(new_in_theirs)} records from theirs"],
                None,
            )

        return False, ours, [], MergeConflict(
            path=file_name,
            domain="database",
            description=f"Automated 3-way merge not supported for binary SQLite file {file_name}",
        )

    # --- LINE-BASED 3-WAY DIFF3 HELPER ---

    def _line_3way_merge(
        self, base_text: str, ours_text: str, theirs_text: str, file_name: str
    ) -> Tuple[str, Optional[MergeConflict]]:
        """Line-based 3-way merge."""
        b_lines = base_text.splitlines(keepends=True)
        o_lines = ours_text.splitlines(keepends=True)
        t_lines = theirs_text.splitlines(keepends=True)

        matcher_o = difflib.SequenceMatcher(None, b_lines, o_lines)
        matcher_t = difflib.SequenceMatcher(None, b_lines, t_lines)

        # If one side didn't change, return the other side
        if o_lines == b_lines:
            return theirs_text, None
        if t_lines == b_lines:
            return ours_text, None

        # Check for simple append/prepend non-interference
        diff_o = [l for l in difflib.unified_diff(b_lines, o_lines)]
        diff_t = [l for l in difflib.unified_diff(b_lines, t_lines)]

        # If both just appended lines to the end
        if ours_text.startswith(base_text) and theirs_text.startswith(base_text):
            o_app = ours_text[len(base_text) :]
            t_app = theirs_text[len(base_text) :]
            return base_text + o_app + ("\n" if not o_app.endswith("\n") else "") + t_app, None

        # Otherwise indicate conflict
        conflict = MergeConflict(
            path=file_name,
            domain="source-code",
            description=f"Overlapping line changes in {file_name}",
        )
        return ours_text, conflict
