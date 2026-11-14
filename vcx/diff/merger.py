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
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple
import xml.etree.ElementTree as ET
import zipfile

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
        if (
            file_type.startswith("cad/")
            or file_name.lower().endswith((".fcstd", ".fcproj"))
            or (
                file_name.lower().endswith(".xml")
                and (b"<Document" in (ours_bytes or b"") or b"<Document" in (theirs_bytes or b""))
            )
        ):
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
        class PortDef(NamedTuple):
            name: str
            direction: str
            width: str
            raw: str = ""

        def extract_ports(ports_str: str) -> List[PortDef]:
            if not ports_str:
                return []
            ports = []
            last_dir = ""
            last_width = ""
            for p in ports_str.split(","):
                clean = " ".join(p.split()).strip()
                if not clean:
                    continue
                pm = re.match(
                    r"^(?P<dir>input\s+wire|input\s+reg|input|output\s+wire|output\s+reg|output|inout\s+wire|inout\s+reg|inout)?\s*"
                    r"(?P<width>\[[^\]]+\])?\s*"
                    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)$",
                    clean,
                )
                if pm:
                    dir_raw = pm.group("dir") or last_dir
                    norm_dir = (
                        "input" if "input" in dir_raw
                        else ("output" if "output" in dir_raw
                        else ("inout" if "inout" in dir_raw else dir_raw))
                    )
                    width = pm.group("width") or (last_width if not pm.group("dir") else "")
                    name = pm.group("name")
                    if pm.group("dir"):
                        last_dir = pm.group("dir")
                        last_width = pm.group("width") or ""
                    ports.append(PortDef(name=name, direction=norm_dir, width=width, raw=clean))
                else:
                    ports.append(PortDef(name=clean, direction="", width="", raw=clean))
            return ports

        def parse_module(text: str):
            m_mod = re.search(r"\bmodule\s+", text)
            preamble = text[:m_mod.start()] if m_mod else ""
            m = re.search(
                r"\bmodule\s+([a-zA-Z0-9_]+)\s*(#\s*\([^;]*?\))?\s*\((.*?)\);(.*?)endmodule",
                text,
                re.DOTALL,
            )
            if not m:
                return None
            return {
                "preamble": preamble,
                "name": m.group(1),
                "params": (m.group(2) or "").strip(),
                "ports_str": m.group(3),
                "body": m.group(4).strip(),
            }

        o_mod = parse_module(ours_text)
        t_mod = parse_module(theirs_text)
        b_mod = parse_module(base_text) if base_text.strip() else None

        if o_mod and t_mod:
            b_ports = extract_ports(b_mod["ports_str"]) if b_mod else []
            o_ports = extract_ports(o_mod["ports_str"])
            t_ports = extract_ports(t_mod["ports_str"])

            b_map = {p.name: p for p in b_ports}
            o_map = {p.name: p for p in o_ports}
            t_map = {p.name: p for p in t_ports}

            # Port collision detection
            for name in set(o_map.keys()) & set(t_map.keys()):
                o_p = o_map[name]
                t_p = t_map[name]
                b_p = b_map.get(name)

                o_changed = (b_p is None) or (o_p.direction != b_p.direction or o_p.width != b_p.width)
                t_changed = (b_p is None) or (t_p.direction != b_p.direction or t_p.width != b_p.width)

                if o_changed and t_changed:
                    if o_p.direction != t_p.direction or o_p.width != t_p.width:
                        desc = f"Conflicting definitions for port '{name}': ours is '{o_p.raw}', theirs is '{t_p.raw}'"
                        return (
                            False,
                            b"",
                            [f"Port collision detected on '{name}'"],
                            MergeConflict(path=file_name, domain="eda-port", description=desc),
                        )

            body_base = b_mod["body"] if b_mod else ""
            body_ours = o_mod["body"]
            body_theirs = t_mod["body"]
            merged_body, body_conflict = self._line_3way_merge(body_base, body_ours, body_theirs, file_name)

            if not body_conflict:
                combined_raw = []
                handled_names = set()

                for p in b_ports:
                    name = p.name
                    if name in o_map and name in t_map:
                        o_p = o_map[name]
                        t_p = t_map[name]
                        if t_p.raw != p.raw and o_p.raw == p.raw:
                            combined_raw.append(t_p.raw)
                        else:
                            combined_raw.append(o_p.raw)
                        handled_names.add(name)
                    elif name in o_map:
                        combined_raw.append(o_map[name].raw)
                        handled_names.add(name)
                    elif name in t_map:
                        combined_raw.append(t_map[name].raw)
                        handled_names.add(name)

                new_o_names = []
                for p in o_ports:
                    if p.name not in handled_names:
                        combined_raw.append(p.raw)
                        handled_names.add(p.name)
                        new_o_names.append(p.name)

                new_t_names = []
                for p in t_ports:
                    if p.name not in handled_names:
                        combined_raw.append(p.raw)
                        handled_names.add(p.name)
                        new_t_names.append(p.name)

                # Preamble selection
                b_pre = b_mod["preamble"] if b_mod else ""
                o_pre = o_mod["preamble"]
                t_pre = t_mod["preamble"]
                chosen_pre = t_pre if (t_pre.strip() != b_pre.strip() and o_pre.strip() == b_pre.strip()) else o_pre
                preamble = (chosen_pre.rstrip() + "\n\n") if chosen_pre.strip() else ""

                # Parameter selection
                b_param = b_mod["params"] if b_mod else ""
                o_param = o_mod["params"]
                t_param = t_mod["params"]
                if t_param != b_param and o_param == b_param and t_param:
                    param_block = t_param
                elif o_param:
                    param_block = o_param
                elif t_param:
                    param_block = t_param
                elif b_param:
                    param_block = b_param
                else:
                    param_block = ""

                mod_name = o_mod["name"]
                param_str = f" {param_block}" if param_block else ""
                ports_formatted = ",\n    ".join(combined_raw)
                merged_verilog = f"{preamble}module {mod_name}{param_str} (\n    {ports_formatted}\n);\n    {merged_body}\nendmodule\n"
                o_joined = ", ".join(new_o_names)
                t_joined = ", ".join(new_t_names)
                explanations = [
                    f"Merged hardware ports: ours ({o_joined}) and theirs ({t_joined})"
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
