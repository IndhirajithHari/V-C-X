"""Hardware and EDA analyzer for Verilog, SystemVerilog, and Floorplan layouts."""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional, Set

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class EdaHardwareAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_text = old_content.decode("utf-8", errors="replace") if old_content else ""
        new_text = new_content.decode("utf-8", errors="replace") if new_content else ""

        raw_diff = self.compute_text_diff(old_text, new_text, file_name)

        if file_name.endswith(".json") or "floorplan" in file_name.lower():
            old_meta = self._analyze_floorplan(old_text)
            new_meta = self._analyze_floorplan(new_text)
            domain_facts = self._compute_floorplan_delta(old_meta, new_meta)
        else:
            old_meta = self._analyze_hdl(old_text)
            new_meta = self._analyze_hdl(new_text)
            domain_facts = self._compute_hdl_delta(old_meta, new_meta)

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary="",
            domain_facts=domain_facts,
        )

    def _analyze_hdl(self, text: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "modules": {},
            "macros": [],
            "pipeline_stages": [],
            "isa_opcodes": [],
            "loc": len(text.splitlines()),
        }
        if not text.strip():
            return meta

        # Find modules
        mod_pattern = re.compile(
            r"\bmodule\s+([a-zA-Z0-9_]+)\s*(?:#\s*\(([^)]*)\))?\s*\(([^;]*?)\);",
            re.DOTALL,
        )
        for m in mod_pattern.finditer(text):
            mod_name = m.group(1)
            params_raw = m.group(2) or ""
            ports_raw = m.group(3) or ""

            ports = []
            for p in re.finditer(r"(input|output|inout)\s+(?:reg|wire|logic)?\s*(\[[^\]]+\])?\s*([a-zA-Z0-9_]+)", ports_raw):
                direction, width, port_name = p.group(1), (p.group(2) or "1-bit").strip(), p.group(3)
                ports.append(f"{direction} {width} {port_name}")

            meta["modules"][mod_name] = {
                "ports": ports,
                "param_count": len(re.findall(r"parameter\b", params_raw)),
            }

        # Submodule / Macro instantiations: instance_name (e.g., ram_macro u_ram (...))
        macro_pattern = re.compile(r"\b([a-zA-Z0-9_]+)\s+(?:#\([^)]*\)\s+)?([a-zA-Z0-9_]+)\s*\(")
        for m in macro_pattern.finditer(text):
            mod_type = m.group(1)
            inst_name = m.group(2)
            if mod_type not in ("module", "always", "initial", "case", "if", "for", "while", "input", "output", "wire", "reg", "logic"):
                meta["macros"].append(f"{mod_type}:{inst_name}")

        # Pipeline stages detection (e.g. IF, ID, EX, MEM, WB or stage1, stage2)
        pipeline_matches = re.findall(r"\b([a-zA-Z0-9_]*(?:pipeline|stage|alustage|pipe)[a-zA-Z0-9_]*)\b", text, re.IGNORECASE)
        meta["pipeline_stages"] = sorted(list(set(pipeline_matches)))

        # ISA / Opcode decodes
        opcodes = re.findall(r"\b(?:OPCODE|ALU_OP|OP_)[a-zA-Z0-9_]+\b", text)
        meta["isa_opcodes"] = sorted(list(set(opcodes)))

        return meta

    def _analyze_floorplan(self, text: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "macros": {},
            "die_area": None,
            "utilization": None,
        }
        if not text.strip():
            return meta

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                meta["die_area"] = data.get("die_area") or data.get("die_box")
                meta["utilization"] = data.get("utilization") or data.get("core_utilization")
                macros = data.get("macros", {})
                if isinstance(macros, dict):
                    for name, props in macros.items():
                        if isinstance(props, dict):
                            meta["macros"][name] = {
                                "x": props.get("x"),
                                "y": props.get("y"),
                                "orientation": props.get("orientation") or props.get("orient"),
                            }
                elif isinstance(macros, list):
                    for item in macros:
                        if isinstance(item, dict) and "name" in item:
                            meta["macros"][item["name"]] = {
                                "x": item.get("x"),
                                "y": item.get("y"),
                                "orientation": item.get("orientation"),
                            }
        except json.JSONDecodeError:
            pass

        return meta

    def _compute_hdl_delta(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        old_mods = set(old_meta.get("modules", {}).keys())
        new_mods = set(new_meta.get("modules", {}).keys())

        added_mods = sorted(list(new_mods - old_mods))
        removed_mods = sorted(list(old_mods - new_mods))

        modified_ports = []
        for mod in (old_mods & new_mods):
            if old_meta["modules"][mod].get("ports") != new_meta["modules"][mod].get("ports"):
                modified_ports.append(mod)

        old_macros = set(old_meta.get("macros", []))
        new_macros = set(new_meta.get("macros", []))

        old_isa = set(old_meta.get("isa_opcodes", []))
        new_isa = set(new_meta.get("isa_opcodes", []))

        return {
            "added_modules": added_mods,
            "removed_modules": removed_mods,
            "modified_ports": modified_ports,
            "added_macros": sorted(list(new_macros - old_macros)),
            "removed_macros": sorted(list(old_macros - new_macros)),
            "isa_opcode_delta": sorted(list(new_isa - old_isa)),
            "pipeline_stages": new_meta.get("pipeline_stages", []),
        }

    def _compute_floorplan_delta(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        old_m = old_meta.get("macros", {})
        new_m = new_meta.get("macros", {})

        moved_macros = []
        for name in set(old_m.keys()) & set(new_m.keys()):
            o_pos = (old_m[name].get("x"), old_m[name].get("y"))
            n_pos = (new_m[name].get("x"), new_m[name].get("y"))
            if o_pos != n_pos:
                moved_macros.append(f"{name} relocated from {o_pos} to {n_pos}")

        return {
            "moved_macros": moved_macros,
            "added_macros": sorted(list(set(new_m.keys()) - set(old_m.keys()))),
            "removed_macros": sorted(list(set(old_m.keys()) - set(new_m.keys()))),
            "utilization_delta": (
                (new_meta.get("utilization") or 0) - (old_meta.get("utilization") or 0)
                if new_meta.get("utilization") is not None and old_meta.get("utilization") is not None
                else None
            ),
        }
